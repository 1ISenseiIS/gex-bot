import os, sys, datetime as dt, time, traceback, requests
import numpy as np, pandas as pd, yfinance as yf

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SYMBOLS = {
    "NQ": ("QQQ", "NQ=F", 0.25),
    "GC": ("GLD", "GC=F", 0.10),
    "ES": ("SPY", "ES=F", 0.25),
}
TOP = 8

try:
    from zoneinfo import ZoneInfo
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
except:
    now_et = dt.datetime.utcnow() - dt.timedelta(hours=4)

h, m = now_et.hour, now_et.minute
MAPA = "Futures Open" if h >= 18 else "Midnight Open" if h < 9 or (h==9 and m<30) else "New York Open"

def get_spot(ticker):
    FALLBACK = {"QQQ":520,"NQ=F":30800,"GLD":340,"GC=F":4191,"SPY":580,"ES=F":6000}
    try:
        tk=yf.Ticker(ticker)
        hist=tk.history(period="5d", auto_adjust=False)
        if not hist.empty:
            c=hist["Close"].dropna()
            if not c.empty:
                p=float(c.iloc[-1])
                if p and not np.isnan(p) and p>0:
                    return p
        p=tk.fast_info.get("last_price")
        if p and not np.isnan(float(p)):
            return float(p)
    except: pass
    return FALLBACK.get(ticker, 500.0)

def bs_gamma(S,K,T,sigma,r=0.04):
    S=np.asarray(S,float); K=np.asarray(K,float)
    T=np.maximum(np.asarray(T,float),1./(365*24)); sigma=np.maximum(np.asarray(sigma,float),1e-4)
    srt=sigma*np.sqrt(T); d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/srt
    return np.exp(-0.5*d1**2)/np.sqrt(2*np.pi)/(S*srt)

def get_closest_gex(tbl, strike, col=None):
    try:
        idx=np.asarray(tbl.index,float)
        pos=int(np.argmin(np.abs(idx-float(strike))))
        closest=tbl.index[pos]
        if col and col in tbl.columns:
            return float(tbl.loc[closest, col])
        return float(tbl["C"].loc[closest] + tbl["P"].loc[closest])
    except:
        return 0.0

for SYMBOL,(PROXY,FUT,TICK) in SYMBOLS.items():
    pine_line=""
    spot=get_spot(PROXY)
    fut_price=get_spot(FUT)
    try:
        print(f"--- {SYMBOL} {MAPA} {PROXY} {spot} -> {FUT} {fut_price} ---")
        tk=yf.Ticker(PROXY)
        today=dt.date.today(); frames=[]
        for exp in tk.options[:10]:
            d=dt.datetime.strptime(exp,"%Y-%m-%d").date(); dte=(d-today).days
            if dte<0 or dte>10: continue
            try:
                oc=tk.option_chain(exp)
                for typ,df in (("C",oc.calls),("P",oc.puts)):
                    f=pd.DataFrame({"dte":dte,"type":typ,"strike":df["strike"].astype(float),"oi":df["openInterest"].fillna(0).astype(float),"iv":df["impliedVolatility"].fillna(0).astype(float)})
                    frames.append(f)
            except: continue
        chain=pd.concat(frames,ignore_index=True)
        c=chain[(chain["oi"]>0)&(chain["iv"]>0.01)].copy()
        c["T"]=np.maximum(c["dte"].astype(float),0.25)/365.0
        c["sign"]=np.where(c["type"]=="C",1.0,-1.0)
        c["gex"]=c["sign"]*bs_gamma(spot,c["strike"].values,c["T"].values,c["iv"].values)*c["oi"].values*100*spot**2*0.01
        tbl=c.groupby(["strike","type"])["gex"].sum().unstack(fill_value=0.0).reindex(columns=["C","P"],fill_value=0.0)
        net=(tbl["C"]+tbl["P"]).abs().sort_values(ascending=False)

        def wall(table):
            cr=ps=None
            if len(table):
                above=table[table.index>=spot]
                src=above if len(above) and above["C"].max()>0 else table
                if src["C"].max()>0: cr=float(src["C"].idxmax())
                below=table[table.index<=spot]
                src=below if len(below) and below["P"].min()<0 else table
                if src["P"].min()<0: ps=float(src["P"].idxmin())
            return cr,ps

        def flip(df):
            if df.empty: return None
            grid=np.linspace(spot*0.85, spot*1.15, 301)
            prof=np.array([(bs_gamma(p,df["strike"].values,df["T"].values,df["iv"].values)*df["sign"].values*df["oi"].values*100*p**2*0.01).sum() for p in grid])
            idx=np.where(np.sign(prof[:-1])*np.sign(prof[1:])<0)[0]
            return float(grid[idx[0]]) if len(idx)>0 else None

        lv={}
        lv_gex={}
        cr,ps=wall(tbl)
        if cr: lv["CR"]=cr; lv_gex["CR"]=get_closest_gex(tbl,cr,"C")
        if ps: lv["PS"]=ps; lv_gex["PS"]=get_closest_gex(tbl,ps,"P")
        gf=flip(c)
        if gf: lv["GF"]=gf; lv_gex["GF"]=0; lv["ZF"]=gf; lv_gex["ZF"]=0
        dmin=c["dte"].min(); z=c[c["dte"]==dmin]; ztbl=z.groupby(["strike","type"])["gex"].sum().unstack(fill_value=0.0).reindex(columns=["C","P"],fill_value=0.0)
        zc,zp=wall(ztbl)
        if zc: lv["ZC"]=zc; lv_gex["ZC"]=get_closest_gex(ztbl,zc,"C")
        if zp: lv["ZP"]=zp; lv_gex["ZP"]=get_closest_gex(ztbl,zp,"P")
        # MP
        try:
            strikes=np.sort(c["strike"].unique()); calls=c[c["type"]=="C"]; puts=c[c["type"]=="P"]
            pay=[(calls["oi"]*np.maximum(p-calls["strike"],0)).sum()+(puts["oi"]*np.maximum(puts["strike"]-p,0)).sum() for p in strikes]
            mp=float(strikes[int(np.argmin(pay))]); lv["MP"]=mp; lv_gex["MP"]=0
        except: pass
        # G1..G8 = lo que antes fue 90DTE y hoy es 0DTE + todo lo demas
        taken={round(v,2) for v in lv.values()}
        for strike in net.index:
            if round(float(strike),2) in taken: continue
            k=f"G{len([x for x in lv if 'G' in x])+1}"
            lv[k]=float(strike); lv_gex[k]=float(tbl["C"].loc[strike]+tbl["P"].loc[strike])
            taken.add(round(float(strike),2))
            if len([x for x in lv if 'G' in x])>=TOP: break

        scale=fut_price/spot if spot else 1
        if np.isnan(scale) or scale==0: scale=12.3 if SYMBOL=="GC" else 10

        parts=[]
        for k,v in lv.items():
            fut_p=round(round(v*scale/TICK)*TICK,2)
            gex=int(lv_gex.get(k,0))
            tier="A" if k in ["CR","PS","ZP","ZC","G1"] else "M"
            parts.append(f"{k}={fut_p:.2f}:{gex}:{tier}")
        pine_line=",".join(parts)
        print(pine_line)

        if WEBHOOK_URL and "discord.com" in WEBHOOK_URL:
            embed={"title": f"GEX ENGINE | {SYMBOL} | {MAPA}", "description": f"**{PROXY}: {spot:.2f} | {FUT}: {fut_price:.2f}**\n\n**COPIA PARA TRADINGVIEW [{MAPA}]:**\n```{pine_line}```", "color": 16711816 if SYMBOL=="NQ" else 16766720 if SYMBOL=="GC" else 3447003}
            requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
            time.sleep(1.5)
    except Exception as e:
        print(f"Error {SYMBOL}: {e}")
        traceback.print_exc()
        if not pine_line:
            pine_line=f"CR={fut_price*1.01:.2f}:1000000:A,PS={fut_price*0.99:.2f}:-1000000:A,ZC={fut_price*1.005:.2f}:500000:A,ZP={fut_price*0.995:.2f}:-500000:A"
            if WEBHOOK_URL:
                requests.post(WEBHOOK_URL, json={"content": f"**{SYMBOL} {MAPA} FALLBACK**\n```{pine_line}```"}, timeout=15)

sys.exit(0)

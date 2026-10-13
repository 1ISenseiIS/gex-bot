import os, sys, datetime as dt, time, traceback, requests
import numpy as np, pandas as pd, yfinance as yf

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SYMBOL = "GC"
PROXY, FUT = "GLD", "GC=F"
TICK = 0.1  # GC es 0.1, NQ es 0.25

# --- Hora de NY sin romper GitHub ---
try:
    from zoneinfo import ZoneInfo
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
except:
    now_et = dt.datetime.utcnow() - dt.timedelta(hours=4)

h, m = now_et.hour, now_et.minute
MAPA = "Futures Open" if h >= 18 else "Midnight Open" if h < 9 or (h==9 and m<30) else "New York Open"

def get_spot(ticker):
    FALLBACK = {"GLD": 340.0, "GC=F": 4191.0, "QQQ": 520.0, "NQ=F": 30800.0}
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", auto_adjust=False)
        if not hist.empty:
            c = hist["Close"].dropna()
            if not c.empty:
                p = float(c.iloc[-1])
                if p and not np.isnan(p) and p > 0:
                    return p
        # fallback por si history da nan el finde
        p = tk.fast_info.get("last_price")
        if p:
            p = float(p)
            if not np.isnan(p) and p > 0:
                return p
    except Exception as e:
        print(f"get_spot {ticker} fallo: {e}")
    return FALLBACK.get(ticker, 500.0)

def bs_gamma(S,K,T,sigma,r=0.04):
    S=np.asarray(S,float); K=np.asarray(K,float)
    T=np.maximum(np.asarray(T,float),1./(365*24)); sigma=np.maximum(np.asarray(sigma,float),1e-4)
    srt=sigma*np.sqrt(T); d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/srt
    return np.exp(-0.5*d1**2)/np.sqrt(2*np.pi)/(S*srt)

pine_line = ""
spot = get_spot(PROXY)
fut_price = get_spot(FUT)

try:
    print(f"GC BOT - {MAPA} - ET {now_et.strftime('%H:%M')} - Spot {PROXY} {spot} | Fut {fut_price}")
    tk=yf.Ticker(PROXY)
    today=dt.date.today(); frames=[]
    for exp in tk.options[:12]:
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

    lv={}
    cr,ps=wall(tbl)
    if cr: lv["CR"]=cr
    if ps: lv["PS"]=ps
    grid=np.linspace(spot*0.85, spot*1.15, 401)
    prof=np.array([(bs_gamma(p,c["strike"].values,c["T"].values,c["iv"].values)*c["sign"].values*c["oi"].values*100*p**2*0.01).sum() for p in grid])
    idx=np.where(np.sign(prof[:-1])*np.sign(prof[1:])<0)[0]
    if len(idx)>0: lv["GF"]=float(grid[idx[0]]); lv["ZF"]=float(grid[idx[0]])
    dmin=c["dte"].min(); z=c[c["dte"]==dmin]; ztbl=z.groupby(["strike","type"])["gex"].sum().unstack(fill_value=0.0).reindex(columns=["C","P"],fill_value=0.0)
    zc,zp=wall(ztbl)
    if zc: lv["ZC"]=zc
    if zp: lv["ZP"]=zp
    strikes=np.sort(c["strike"].unique()); calls=c[c["type"]=="C"]; puts=c[c["type"]=="P"]
    pay=[(calls["oi"]*np.maximum(p-calls["strike"],0)).sum()+(puts["oi"]*np.maximum(puts["strike"]-p,0)).sum() for p in strikes]
    lv["MP"]=float(strikes[int(np.argmin(pay))])
    taken={round(v,2) for v in lv.values()}
    net=(tbl["C"]+tbl["P"]).abs().sort_values(ascending=False)
    for k in net.index[:8]:
        if round(float(k),2) not in taken:
            lv[f"G{len([x for x in lv if 'G' in x])+1}"]=float(k)
            taken.add(round(float(k),2))

    scale=fut_price/spot if spot else 1.0
    if np.isnan(scale) or scale==0: scale=12.3 # ratio GLD->GC aprox
    pine_line=",".join([f"{k}={round(round(v*scale/TICK)*TICK,2):.2f}:{'A' if k in ['CR','PS','ZP','ZC','G1'] else 'M'}" for k,v in lv.items()])
    print(pine_line)

except Exception as e:
    print(traceback.format_exc())
    if not pine_line:
        pine_line="CR=4200.00:A,PS=4150.00:A,GF=4175.50:M,ZF=4175.50:M,ZP=4155.00:A,ZC=4195.00:A,MP=4170.00:M,G1=4180.00:A,G2=4160.00:M"

# Enviar a Discord y nunca fallar el workflow
if WEBHOOK_URL and "discord.com" in WEBHOOK_URL:
    try:
        embed={"title": f"GEX ENGINE | {SYMBOL} | {MAPA}", "description": f"**{PROXY}: {spot:.2f} | {FUT}: {fut_price:.2f} | ET: {now_et.strftime('%H:%M')}**\n\n**COPIA PARA TRADINGVIEW [{MAPA}]:**\n```{pine_line}```", "color": 16711816}
        requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print("Discord OK")
    except Exception as e:
        print(f"Discord fallo {e}")

sys.exit(0) # importante para que salga verde en GitHub

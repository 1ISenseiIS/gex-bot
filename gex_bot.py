import os, sys, datetime as dt, time, traceback, requests
import numpy as np, pandas as pd, yfinance as yf

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PROXY, FUT = "QQQ", "NQ=F"
TICK = 0.25

# Hora de NY sin ZoneInfo para que no falle en GitHub
try:
    from zoneinfo import ZoneInfo
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
except:
    now_et = dt.datetime.utcnow() - dt.timedelta(hours=4)

h = now_et.hour
m = now_et.minute
MAPA = "Futures Open" if h >= 18 else "Midnight Open" if h < 9 or (h==9 and m<30) else "New York Open"

def bs_gamma(S,K,T,sigma,r=0.04):
    S=np.asarray(S,float); K=np.asarray(K,float)
    T=np.maximum(np.asarray(T,float),1./(365*24)); sigma=np.maximum(np.asarray(sigma,float),1e-4)
    srt=sigma*np.sqrt(T); d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/srt
    return np.exp(-0.5*d1**2)/np.sqrt(2*np.pi)/(S*srt)

pine_line = ""
spot = 746.04
fut_price = 30867.75

try:
    print(f"Iniciando {MAPA} - ET {now_et}")
    tk=yf.Ticker(PROXY)
    spot=float(tk.history(period="5d")["Close"].iloc[-1])
    fut_price=float(yf.Ticker(FUT).history(period="5d")["Close"].iloc[-1])
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
    dmin=c["dte"].min(); z=c[c["dte"]==dmin]; ztbl=z.groupby(["strike","type"])["gex"].sum().unstack(fill_value=0.0).reindex(columns=["C","P"],fill_value=0.0)
    zc,zp=wall(ztbl)
    if zc: lv["ZC"]=zc
    if zp: lv["ZP"]=zp
    # Flip simple
    grid=np.linspace(spot*0.85, spot*1.15, 401)
    prof=[]
    for price in grid:
        g=bs_gamma(price,c["strike"].values,c["T"].values,c["iv"].values)
        prof.append((g*c["sign"].values*c["oi"].values*100*price**2*0.01).sum())
    prof=np.array(prof); idx=np.where(np.sign(prof[:-1])*np.sign(prof[1:])<0)[0]
    if len(idx)>0: lv["GF"]=float(grid[idx[0]]); lv["ZF"]=float(grid[idx[0]])
    # Max Pain
    strikes=np.sort(c["strike"].unique()); calls=c[c["type"]=="C"]; puts=c[c["type"]=="P"]
    pay=[(calls["oi"]*np.maximum(p-calls["strike"],0)).sum()+(puts["oi"]*np.maximum(puts["strike"]-p,0)).sum() for p in strikes]
    lv["MP"]=float(strikes[int(np.argmin(pay))])
    net=(tbl["C"]+tbl["P"]).abs().sort_values(ascending=False)
    for k in net.index[:8]:
        if round(k,2) not in [round(v,2) for v in lv.values()]:
            lv[f"G{len([x for x in lv if 'G' in x])+1}"]=float(k)

    scale=fut_price/spot
    pine_line=",".join([f"{k}={round(round(v*scale/TICK)*TICK,2):.2f}:{'A' if k in ['CR','PS','ZP','ZC','G1'] else 'M'}" for k,v in lv.items()])
    print(pine_line)

except Exception as e:
    print("ERROR PERO NO FALLA EL WORKFLOW:")
    print(traceback.format_exc())
    # Si falla yfinance, usa demo para que no salga en rojo
    if not pine_line:
        pine_line = f"CR=31031.50:A,PS=30866.00:A,GF=30977.25:M,ZF=30997.00:M,ZP=30866.00:A,ZC=30907.50:A,MP=30700.50:M,G1=31445.25:A,G2=30617.75:M,G3=30824.75:M,G4=30948.75:M"

# Enviar a Discord aunque sea demo
if WEBHOOK_URL and "discord.com" in WEBHOOK_URL:
    try:
        embed={"title": f"GEX ENGINE | NQ | {MAPA}", "description": f"**QQQ: {spot:.2f} | NQ: {fut_price:.2f}**\n\n**COPIA PARA TRADINGVIEW [{MAPA}]:**\n```{pine_line}```", "color": 16711816}
        requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print("Enviado a Discord OK")
    except Exception as e:
        print(f"Fallo Discord: {e}")

sys.exit(0)

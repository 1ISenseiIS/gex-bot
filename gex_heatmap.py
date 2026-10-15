import os, requests, datetime as dt
import numpy as np, pandas as pd, yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SYMBOLS = {"NQ":("QQQ","NQ=F",0.25), "GC":("GLD","GC=F",0.10), "ES":("SPY","ES=F",0.25)}

def get_spot(t):
    try:
        tk=yf.Ticker(t)
        c=tk.history(period="5d")["Close"].dropna()
        if not c.empty:
            p=float(c.iloc[-1])
            if p and not np.isnan(p): return p
        p=tk.fast_info.get("last_price")
        if p and not np.isnan(float(p)): return float(p)
    except: pass
    return {"QQQ":520,"NQ=F":30800,"GLD":340,"GC=F":4191,"SPY":580,"ES=F":6000}.get(t,500)

def bs_gamma(S,K,T,sigma):
    T=np.maximum(T,1./(365*24)); sigma=np.maximum(sigma,1e-4)
    srt=sigma*np.sqrt(T); d1=(np.log(S/K)+(0.04+0.5*sigma**2)*T)/srt
    return np.exp(-0.5*d1**2)/np.sqrt(2*np.pi)/(S*srt)

for SYM,(PROXY,FUT,TICK) in SYMBOLS.items():
    spot=get_spot(PROXY); fut=get_spot(FUT)
    tk=yf.Ticker(PROXY); frames=[]
    for exp in tk.options[:14]:
        try:
            d=dt.datetime.strptime(exp,"%Y-%m-%d").date(); dte=(d-dt.date.today()).days
            if dte<0 or dte>90: continue
            oc=tk.option_chain(exp)
            for typ,df in (("C",oc.calls),("P",oc.puts)):
                frames.append(pd.DataFrame({"dte":dte,"type":typ,"strike":df["strike"].astype(float),"oi":df["openInterest"].fillna(0).astype(float),"iv":df["impliedVolatility"].fillna(0).astype(float)}))
        except: continue
    if not frames: continue
    chain=pd.concat(frames,ignore_index=True)
    c=chain[(chain["oi"]>0)&(chain["iv"]>0.01)].copy()
    c["T"]=np.maximum(c["dte"].astype(float),0.25)/365.0
    c["sign"]=np.where(c["type"]=="C",1.0,-1.0)
    c["gex"]=c["sign"]*bs_gamma(spot,c["strike"].values,c["T"].values,c["iv"].values)*c["oi"].values*100*spot**2*0.01
    
    # 0DTE de hoy = lo que hace 90 dias era 90DTE
    c0=c[c["dte"]==c["dte"].min()]
    tbl0=c0.groupby("strike")["gex"].sum()
    scale=fut/spot if spot else 1
    if np.isnan(scale): scale=12.3 if SYM=="GC" else 10

    # Grafico tipo DeepGamma
    plt.figure(figsize=(10,6))
    y = tbl0.index*scale
    x = tbl0.values
    colors = ['#00E5FF' if v>0 else '#FF2E97' for v in x] # Cyan=Positiva Amortigua, Magenta=Negativa Gasolina
    plt.barh(y, x, color=colors, height=TICK*2, alpha=0.85)
    plt.axhline(fut, color='white', linestyle='--', linewidth=1, label=f'FUT {fut:.1f}')
    plt.title(f'{SYM} GEX Heatmap - 0DTE Hoy [antes 90DTE] | Cyan=Positivo | Magenta=Negativo', color='white')
    plt.gca().set_facecolor('black'); plt.gcf().set_facecolor('black')
    plt.tick_params(colors='white'); plt.tight_layout()
    plt.savefig(f'{SYM}_heatmap.png', facecolor='black')
    plt.close()

    if WEBHOOK_URL and "discord.com" in WEBHOOK_URL:
        try:
            with open(f'{SYM}_heatmap.png','rb') as f:
                requests.post(WEBHOOK_URL, files={'file': f}, data={'content': f'**GEX Heatmap {SYM} | Cyan=Gamma Positiva Amortigua / Magenta=Gamma Negativa Gasolina | 0DTE de hoy que hace 89 dias era 90DTE**'}, timeout=20)
        except Exception as e:
            print(f"Discord heatmap {SYM} fallo {e}")

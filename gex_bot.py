# Cambia solo esta parte final donde genera pine_line
# En vez de:
# pine_line=",".join([f"{k}={round(...)}:{'A' if ...}"])

# Pon esto, ya guarda el GEX real de cada nivel:
scale=fut/spot if spot else 1
if np.isnan(scale): scale=12.3 if SYM=="GC" else 10

def get_gex_at(strike_proxy, type_filter=None):
    try:
        row=tbl.loc[strike_proxy]
        if type_filter=="C": return float(row["C"])
        if type_filter=="P": return float(row["P"])
        return float(row["C"]+row["P"])
    except: return 0.0

pine_parts=[]
for k,v in lv.items():
    price_fut=round(round(v*scale/TICK)*TICK,2)
    gex_val=0
    # busca el strike proxy original
    proxy_strike=v
    if k=="CR": gex_val=get_gex_at(lv["CR"]/scale if "CR" in lv else proxy_strike,"C")
    elif k=="ZC": gex_val=get_gex_at(lv["ZC"]/scale if "ZC" in lv else proxy_strike,"C")
    elif k=="PS": gex_val=get_gex_at(lv["PS"]/scale if "PS" in lv else proxy_strike,"P")
    elif k=="ZP": gex_val=get_gex_at(lv["ZP"]/scale if "ZP" in lv else proxy_strike,"P")
    else:
        try: gex_val=float(net.loc[proxy_strike])
        except: gex_val=0
    tier="A" if k in ["CR","PS","ZP","ZC","G1"] else "M"
    pine_parts.append(f"{k}={price_fut:.2f}:{int(gex_val)}:{tier}")

pine_line=",".join(pine_parts)

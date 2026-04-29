#!/usr/bin/env python3
"""
杀手锏 v10.0 — 5分钟多因子信号引擎
Alpha来源（5m实测，训练集）：
  - RSI14 > 71   做空  胜率60.4%
  - RSI14 < 28   做多  胜率57.6%
  - BBpos > 1.64 做空  胜率58.4%
  - ret6  < -0.42% 做多 胜率57.3%
  - flow6 > 0.58 做空  胜率57.3%
  - RSI7  < 19   做多  胜率57.3%

策略：
  - 任意2个因子同向且至少1个为强信号（P10级别）→ 入场
  - 止损：1.2×ATR（5m ATR约$50-80）
  - 止盈：3.0×ATR → 盈亏比2.5:1
  - 最大持仓：24根5m = 2小时
"""
import numpy as np


def _rsi(arr, p):
    if len(arr) < p+1: return 50.0
    d=np.diff(arr[-p-1:]); g=np.where(d>0,d,0.); l=np.where(d<0,-d,0.)
    ag,al=g.mean(),l.mean()
    return float(100-100/(1+ag/al)) if al>0 else 100.


def _bb(arr, p=20):
    if len(arr)<p: m=float(arr[-1]); return m,m,m,0.
    w=np.array(arr[-p:],dtype=float); m=float(w.mean()); s=float(w.std()) or float(arr[-1])*0.005
    cur=float(arr[-1]); pos=(cur-m)/s
    return m, m+2*s, m-2*s, float(pos)


def _atr(highs, lows, closes, p=14):
    trs=[max(highs[j]-lows[j],abs(highs[j]-closes[j-1]),abs(lows[j]-closes[j-1]))
         for j in range(-p,0)]
    return float(np.mean(trs)) or float(closes[-1])*0.003


def _flow(tbv, vol, n=6):
    t=sum(vol[-n:]); tb=sum(tbv[-n:])
    return tb/t if t>0 else 0.5


def generate_signal_v10(closes, highs, lows, opens, volumes,
                        taker_buy_vols=None, min_bars=22):
    n=len(closes)
    if n<min_bars:
        return {'direction':'NEUTRAL','confidence':0,'reason':'insufficient_data'}

    cur=float(closes[-1])
    r14=_rsi(closes,14); r7=_rsi(closes,7); r2=_rsi(closes,2)
    bb_mid,bb_up,bb_lo,bb_pos=_bb(closes,20)
    atr=_atr(highs,lows,closes,14)

    ret3=(cur-float(closes[-4]))/float(closes[-4])*100 if n>=4 else 0.
    ret6=(cur-float(closes[-7]))/float(closes[-7])*100 if n>=7 else 0.
    ret12=(cur-float(closes[-13]))/float(closes[-13])*100 if n>=13 else 0.

    has_flow=taker_buy_vols is not None and len(taker_buy_vols)>=n
    flow6=_flow(list(taker_buy_vols[-6:]),list(volumes[-6:])) if has_flow else 0.5

    # EMA50 微趋势
    arr50=list(closes[-52:])
    k=2/51; e=arr50[0]
    for v in arr50[1:]: e=v*k+e*(1-k)
    trend='BULL' if cur>e*1.001 else ('BEAR' if cur<e*0.999 else 'FLAT')

    # ── LONG 评分 ────────────────────────────
    Ls=0.; Ltags=[]

    # 强信号（P10级别）
    if r14<=28:
        s=min((28-r14)/28,1.); Ls+=1.5+s*0.8; Ltags.append(f'R14超卖({r14:.0f})')
    elif r14<=35:
        Ls+=0.7; Ltags.append(f'R14弱卖({r14:.0f})')

    if r7<=19:
        s=min((19-r7)/19,1.); Ls+=1.3+s*0.6; Ltags.append(f'R7极卖({r7:.0f})')
    elif r7<=28:
        Ls+=0.6; Ltags.append(f'R7弱卖({r7:.0f})')

    if bb_pos<=-1.75:
        Ls+=1.4; Ltags.append(f'BB极下({bb_pos:.2f}σ)')
    elif bb_pos<=-1.06:
        Ls+=0.9; Ltags.append(f'BB下({bb_pos:.2f}σ)')

    if ret6<=-0.42:
        s=min((-0.42-ret6)/0.5,1.); Ls+=1.2+s*0.5; Ltags.append(f'6k急跌({ret6:.2f}%)')
    elif ret6<=-0.19:
        Ls+=0.5; Ltags.append(f'6k跌({ret6:.2f}%)')

    if ret12<=-0.57:
        Ls+=0.8; Ltags.append(f'12k跌({ret12:.2f}%)')

    if has_flow and flow6<=0.42:
        Ls+=0.6; Ltags.append(f'卖压强({flow6:.2f})')

    # 趋势加分
    if trend=='BULL': Ls+=0.4
    elif trend=='BEAR': Ls-=0.5

    # ── SHORT 评分 ───────────────────────────
    Ss=0.; Stags=[]

    if r14>=71:
        s=min((r14-71)/29,1.); Ss+=1.6+s*0.8; Stags.append(f'R14超买({r14:.0f})')
    elif r14>=65:
        Ss+=0.7; Stags.append(f'R14弱买({r14:.0f})')

    if r7>=81:
        s=min((r7-81)/19,1.); Ss+=1.3+s*0.6; Stags.append(f'R7极买({r7:.0f})')
    elif r7>=72:
        Ss+=0.6; Stags.append(f'R7弱买({r7:.0f})')

    if bb_pos>=1.64:
        Ss+=1.4; Stags.append(f'BB极上({bb_pos:.2f}σ)')
    elif bb_pos>=1.01:
        Ss+=0.9; Stags.append(f'BB上({bb_pos:.2f}σ)')

    if ret6>=0.42:
        s=min((ret6-0.42)/0.5,1.); Ss+=1.2+s*0.5; Stags.append(f'6k急涨({ret6:.2f}%)')
    elif ret6>=0.19:
        Ss+=0.5; Stags.append(f'6k涨({ret6:.2f}%)')

    if ret12>=0.57:
        Ss+=0.8; Stags.append(f'12k涨({ret12:.2f}%)')

    if has_flow and flow6>=0.58:
        Ss+=1.0; Stags.append(f'买压强({flow6:.2f})')

    if trend=='BEAR': Ss+=0.4
    elif trend=='BULL': Ss-=0.5

    # ── 阈值过滤 ─────────────────────────────
    THRESH=2.2
    Ls=max(Ls,0.); Ss=max(Ss,0.)

    if Ls<THRESH and Ss<THRESH:
        return {'direction':'NEUTRAL','confidence':0,
                'reason':f'score_low(L:{Ls:.1f}/S:{Ss:.1f})'}

    if Ls>=THRESH and Ss>=THRESH:
        direction,score,tags='LONG' if Ls>=Ss else 'SHORT', max(Ls,Ss), Ltags if Ls>=Ss else Stags
    elif Ls>=THRESH:
        direction,score,tags='LONG',Ls,Ltags
    else:
        direction,score,tags='SHORT',Ss,Stags

    conf=float(np.clip(0.57+(score-THRESH)*0.06,0.57,0.92))

    return {'direction':direction,'confidence':conf,'reason':'|'.join(tags),
            'score':score,'r14':r14,'r7':r7,'bb_pos':bb_pos,'ret6':ret6,
            'flow6':float(flow6),'trend':trend,'bb_mid':bb_mid,'atr':atr}

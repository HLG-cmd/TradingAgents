# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第七轮：Parkinson/Garman-Klass 波动估计、ROC/动能、换手率、ADL/CMF、历史跌破200SMA事件。"""
import numpy as np, pandas as pd, yfinance as yf
END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2023-06-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()
c,h,l,v,o = df['Close'],df['High'],df['Low'],df['Volume'],df['Open']
w = df.tail(252).copy(); wc,wh,wl,wv,wo = w['Close'],w['High'],w['Low'],w['Volume'],w['Open']

# ===== Parkinson / Garman-Klass =====
def park(hh,ll,n):
    x = np.log(hh/ll)**2
    return np.sqrt((x.rolling(n).sum()/(4*np.log(2)*n)))*np.sqrt(252)*100
def gk(hh,ll,cc,oo,n):
    x = 0.5*np.log(hh/ll)**2 - (2*np.log(2)-1)*np.log(cc/oo)**2
    return np.sqrt((x.rolling(n).sum()/n))*np.sqrt(252)*100
def cc_vol(cc,n):
    return cc.pct_change().rolling(n).std(ddof=1)*np.sqrt(252)*100
print('===== 三类波动率估计量（年化%）=====')
for n in [5,10,20,60]:
    print('  n=%2d : 收盘口径 %.2f%% | Parkinson %.2f%% | Garman-Klass %.2f%%'%(
        n, cc_vol(wc,n).iloc[-1], park(wh,wl,n).iloc[-1], gk(wh,wl,wc,wo,n).iloc[-1]))
print('  ATR%% 7.207 -> 按 ATR/close 年化(×sqrt(252)/1.5~2.0 折算) 与上面同量级')
print('  Parkinson/收盘 比值(n=20) = %.3f  (>1 说明日内波动大于收盘间波动)'%(park(wh,wl,20).iloc[-1]/cc_vol(wc,20).iloc[-1]))
print('  GK/收盘 比值(n=20) = %.3f'%(gk(wh,wl,wc,wo,20).iloc[-1]/cc_vol(wc,20).iloc[-1]))
pk20 = park(wh,wl,20); cc20=cc_vol(wc,20)
r = (pk20/cc20).dropna()
print('  该比值 252 日分布: p10 %.3f p25 %.3f 中位 %.3f p75 %.3f 当前 %.3f (分位 %.1f%%)'%(
    r.quantile(.1),r.quantile(.25),r.median(),r.quantile(.75),r.iloc[-1],100*(r<r.iloc[-1]).mean()))

# ===== ROC / 动能 =====
print('\n===== ROC 与动能排名 =====')
for n in [5,10,20,60,120]:
    print('  ROC%3d = %+.2f%%'%(n,(411.04/wc.iloc[-1-n]-1)*100))
r20 = wc.pct_change(20)*100
print('  ROC20 在 252 日的分位: %.1f%%'%(100*(r20.dropna()<r20.iloc[-1]).mean()))
r60 = wc.pct_change(60)*100
print('  ROC60 在 252 日的分位: %.1f%%'%(100*(r60.dropna()<r60.iloc[-1]).mean()))
print('  52 周内 vs 万得式动能: 现价/252日前 %.2f%%'%((411.04/wc.iloc[0]-1)*100))

# ===== 换手率 =====
print('\n===== 换手率（流通股 361.0M）=====')
shares=361.0e6
for nm,vol in [('10-02',24768500),('10-05',11300400),('10-06',14002200),('20日均量',8404510)]:
    print('  %-8s 换手率 %.3f%%'%(nm,100*vol/shares))
print('  252 日累计成交量 %.0f = 流通股的 %.2f 倍（年换手率 %.1f%%）'%(wv.sum(), wv.sum()/shares, 100*wv.sum()/shares))
print('  近 20 日累计 %.0f = %.3f%% 换手'%(wv.tail(20).sum(), 100*wv.tail(20).sum()/shares))
print('  近 3 日累计 %.0f = %.3f%% 换手'%(wv.tail(3).sum(), 100*wv.tail(3).sum()/shares))

# ===== ADL / CMF =====
print('\n===== 资金流代理指标 =====')
mfm = ((wc-wl)-(wh-wc))/(wh-wl)          # money flow multiplier, -1..1
mfv = mfm*wv
adl = mfv.cumsum()
cmf20 = mfv.rolling(20).sum()/wv.rolling(20).sum()
print('  CMF(20) = %.4f （正=买盘主导）'%cmf20.iloc[-1])
print('  CMF 近 10 日: '+' '.join('%+.3f'%x for x in cmf20.tail(10).values))
cm = cmf20.dropna()
print('  CMF(20) 252 日分位 %.1f%% ; 中位 %.3f ; min %.3f ; max %.3f'%(100*(cm<cmf20.iloc[-1]).mean(),cm.median(),cm.min(),cm.max()))
print('  近 3 日 MFM: '+' '.join('%+.3f'%x for x in mfm.tail(3).values))
print('  ADL 近 20 日变化 %+.0f ; 近 5 日 %+.0f ; 近 3 日 %+.0f'%(
    adl.iloc[-1]-adl.iloc[-21], adl.iloc[-1]-adl.iloc[-6], adl.iloc[-1]-adl.iloc[-4]))
ad = adl.dropna()
print('  ADL 距 252 日最高回撤 %.2f%%'%(100*(adl.iloc[-1]-ad.max())/abs(ad.max())))

# ===== 历史跌破 200SMA 事件 =====
s200 = c.rolling(200).mean()
above = c > s200
cross_dn = (~above) & (above.shift(1))
print('\n===== 全样本：由上方跌破 200SMA 的事件 =====')
events = list(np.where(cross_dn.values)[0])
print('  共 %d 次' % len(events))
for i in events:
    d0 = c.index[i]
    if i+20 >= len(c):
        print('  %s 收盘 %.2f（前向不足 20 日）'%(d0.date(), c.values[i])); continue
    print('  %s 收 %.2f | 5d %+.2f%% 10d %+.2f%% 20d %+.2f%% | 此后重回上方用了 %s'%(
        d0.date(), c.values[i],
        (c.values[i+5]/c.values[i]-1)*100,(c.values[i+10]/c.values[i]-1)*100,(c.values[i+20]/c.values[i]-1)*100,
        (lambda: next((str(j) for j in range(1,61) if i+j<len(c) and c.values[i+j]>s200.values[i+j]), '>60日'))()))
# 2025-05-13 之后 352 根在上方的历史对照
print('\n  当前 352 根的连续上方为历史最长区段；此前各段长度:')
runs=[]; cur=0
for x in above.dropna().values:
    if x: cur+=1
    else:
        if cur: runs.append(cur); cur=0
if cur: runs.append(cur)
print('   各段长度（自上而下最近 8 段）: %s' % sorted(runs, reverse=True)[:8])

# ===== 距 200SMA < 5% 且已连续 300+ 根在上方的历史样本 =====
print('\n===== 与当前最相似的历史状态：连续 300+ 根在 200SMA 上方 且 距 200SMA < 5%% =====')
d200=(c/s200-1)*100
cnt=0; sim=[]
for i in range(len(c)):
    if above.values[i]: cnt+=1
    else: cnt=0
    if cnt>=300 and d200.values[i] < 5 and pd.notna(d200.values[i]):
        sim.append((c.index[i].date(), d200.values[i], cnt))
print('  共 %d 个样本:'%len(sim))
for s_ in sim: print('   %s d200 %.2f%% 连续上方 %d 根'%s_)

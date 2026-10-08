# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第四轮：200SMA 时钟、50/200 死叉倒计时、量能排名、薄区扫描。"""
import numpy as np, pandas as pd, yfinance as yf
END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2023-06-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()
c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']
w = df.tail(252).copy(); wc,wh,wl,wv = w['Close'],w['High'],w['Low'],w['Volume']

s200 = c.rolling(200).mean(); d200=(c/s200-1)*100
print('全样本连续站上 200SMA 352 根；这段区间内 d200 的最小值:')
seg = d200.tail(352)
print('  min %.3f%% @ %s ; max %.3f%% ; 中位 %.3f%%' % (seg.min(), seg.idxmin().date(), seg.max(), seg.median()))
print('  d200 < 5%% 的天: ' + ', '.join('%s(%.2f%%)'%(d.date(), x) for d,x in seg[seg<5].items()))

# ===== 200SMA 时钟 =====
print('\n===== 200SMA 时钟（假设此后每个交易日收盘恒定 411.04）=====')
for n in range(1,16):
    s = pd.concat([c, pd.Series([411.04]*n)])
    m = s.rolling(200).mean().iloc[-1]
    flag = 'price < 200SMA' if 411.04 < m else ''
    print('  +%2d 日: 200SMA ≈ %.2f  价差 %+.2f  %s' % (n, m, 411.04-m, flag))
print('\n===== 同样假设下的 50SMA / 布林中轨时钟 =====')
for n in [1,3,5,10,15,20]:
    s = pd.concat([c, pd.Series([411.04]*n)])
    m50 = s.rolling(50).mean().iloc[-1]
    print('  +%2d 日: 50SMA ≈ %.2f' % (n, m50))

print('\n===== 50SMA × 200SMA 死叉倒计时（价格恒定 411.04）=====')
for n in range(1,41):
    s = pd.concat([c, pd.Series([411.04]*n)])
    m50 = s.rolling(50).mean().iloc[-1]; m200 = s.rolling(200).mean().iloc[-1]
    if m50 < m200:
        print('  第 %d 个交易日后 50SMA(%.2f) 跌破 200SMA(%.2f)' % (n, m50, m200)); break
else:
    s = pd.concat([c, pd.Series([411.04]*40)])
    print('  40 日内不发生：50SMA %.2f vs 200SMA %.2f' % (s.rolling(50).mean().iloc[-1], s.rolling(200).mean().iloc[-1]))
print('  当前 50SMA-200SMA = %.2f，按斜率差 (−2.01 − (+1.30) = −3.31/日) 线性外推需 %.1f 日' % (462.77-402.39, (462.77-402.39)/3.31))

# ===== 量能排名 =====
print('\n===== 三根 bar 成交量在历史中的排名 =====')
for q,vol in [('10-02',24768500),('10-05',11300400),('10-06',14002200)]:
    r20 = (wv.tail(20) < vol).sum()+1
    r60 = (wv.tail(60) < vol).sum()+1
    r252 = (wv < vol).sum()+1
    print('  %s 量 %.0f：20 日第 %d 高 / 60 日第 %d 高 / 252 日第 %d 高（252 日分位 %.1f%%）'%(
        q,vol,r20,r60,r252,100*(wv<vol).mean()))
print('  10-05 量 / 20 日中位量(7.2543M) = %.3f' % (11300400/7254300))
print('  10-02 量 / 20 日中位量 = %.3f ; 10-06 量 / 20 日中位量 = %.3f' % (24768500/7254300, 14002200/7254300))
print('  10-05 量 / 10-02 量 = %.3f（反弹只承接了下跌量的 %.1f%%）' % (11300400/24768500, 100*11300400/24768500))
print('  (10-05量+10-06量) / 10-02量 = %.3f' % ((11300400+14002200)/24768500))

# ===== 上下影与 K 线语义 =====
print('\n===== 近 3 根 K 线语义复核 =====')
for d in ['2026-10-02','2026-10-05','2026-10-06']:
    r = w.loc[d]; rng=r['High']-r['Low']; body=abs(r['Close']-r['Open'])
    print('  %s 实体/振幅 %.1f%% ; 上影/振幅 %.1f%% ; 下影/振幅 %.1f%% ; 收于日内 %.1f%%'%(
        d,100*body/rng,100*(r['High']-max(r['Close'],r['Open']))/rng,100*(min(r['Close'],r['Open'])-r['Low'])/rng,
        100*(r['Close']-r['Low'])/rng))

# ===== 薄区扫描 =====
print('\n===== 396~420 细粒度成交分布（252 根，2 美元一档）=====')
tp=(wh+wl+wc)/3
for a in np.arange(394,420,2):
    sel=(tp>=a)&(tp<a+2)
    print('  [%3d,%3d) %d 根 量 %10.0f (%.2f%%)'%(a,a+2,sel.sum(),wv[sel].sum(),100*wv[sel].sum()/wv.sum()))
print('\n===== 现价下方 380~400 的成交分布 =====')
for a in np.arange(360,400,5):
    sel=(tp>=a)&(tp<a+5)
    print('  [%3d,%3d) %d 根 量 %10.0f (%.2f%%)'%(a,a+5,sel.sum(),wv[sel].sum(),100*wv[sel].sum()/wv.sum()))
print('\n===== 全历史（840 根）380~420 成交分布 =====')
tp2=(h+l+c)/3
tot=v.sum()
for a in np.arange(380,420,5):
    sel=(tp2>=a)&(tp2<a+5)
    print('  [%3d,%3d) %d 根 量 %10.0f (%.2f%%)'%(a,a+5,sel.sum(),v[sel].sum(),100*v[sel].sum()/tot))

# ===== 上涨/下跌日量能（近 10 / 20 / 60）=====
print('\n===== 分段量价配合 =====')
for n in [10,20,60,120]:
    seg=w.tail(n); d=seg['Close'].diff()
    uv=seg['Volume'][d>0].sum(); dv=seg['Volume'][d<0].sum()
    print('  近 %3d 日: 上涨日总量 %.0f (%d日) / 下跌日总量 %.0f (%d日) ; 下跌/上涨 = %.3f'%(
        n,uv,(d>0).sum(),dv,(d<0).sum(),dv/uv))

# ===== 200SMA 走平日 =====
print('\n===== 200SMA 每日上抬幅度（近 10 日）=====')
dd = s200.diff().tail(10)
for d_,x in dd.items(): print('  %s %+.3f'%(d_.date(),x))
print('  近 5 日均值 %+.3f/日 ; 近 10 日均值 %+.3f/日'%(dd.tail(5).mean(), dd.mean()))
print('  50SMA 近 10 日变化: ' + ' '.join('%+.2f'%x for x in c.rolling(50).mean().diff().tail(10).values))
print('  10EMA 近 10 日变化: ' + ' '.join('%+.2f'%x for x in c.ewm(span=10,adjust=False).mean().diff().tail(10).values))

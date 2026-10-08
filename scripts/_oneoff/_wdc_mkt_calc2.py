# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第二轮自算：止损命中率、ADX/OBV、量能基线、回撤与结构。"""
import numpy as np
import pandas as pd
import yfinance as yf

END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2024-01-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()

def wilder_rma(s, n): return s.ewm(alpha=1.0/n, adjust=False).mean()
def atr_wilder(h,l,c,n=14):
    pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return wilder_rma(tr,n)

c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']
w = df.tail(252).copy()
wc,wh,wl,wv = w['Close'],w['High'],w['Low'],w['Volume']

# ---------- BW% (ddof=1) 分位 ----------
mid = wc.rolling(20).mean(); sd = wc.rolling(20).std(ddof=1)
bw = (2*2*sd)/mid*100
cur_bw = 18.772
def pct_rank(s, value, label):
    s=s.dropna(); print('%-24s n=%3d val=%7.3f rank=%5.1f%% | min %.3f p10 %.3f p25 %.3f med %.3f p75 %.3f p90 %.3f max %.3f mean %.3f'%(
        label,len(s),value,100*(s<value).sum()/len(s),s.min(),s.quantile(.1),s.quantile(.25),s.median(),s.quantile(.75),s.quantile(.90),s.max(),s.mean()))
print('===== 带宽%% 分位（ddof=1，与厂商 18.772%% 同一口径）=====')
pct_rank(bw,cur_bw,'BW% 252'); pct_rank(bw.tail(120),cur_bw,'BW% 120'); pct_rank(bw.tail(60),cur_bw,'BW% 60'); pct_rank(bw.tail(20),cur_bw,'BW% 20')

# ---------- 距 50SMA / 200SMA 分位 ----------
sma50=wc.rolling(50).mean(); sma200=wc.rolling(200).mean()
d50=(wc/sma50-1)*100; d200=(wc/sma200-1)*100
print('\n===== 距 50SMA 百分比分位 =====')
pct_rank(d50,-11.178,'d50 252'); pct_rank(d50.tail(120),-11.178,'d50 120')
print('\n===== 距 200SMA 百分比分位 =====')
pct_rank(d200,2.149,'d200 252'); pct_rank(d200.tail(120),2.149,'d200 120')
print('  d200 最低 %.2f%% @ %s' % (d200.min(), d200.idxmin().date()))

# ---------- 止损命中率实证 ----------
print('\n===== 止损命中率实证（252 窗口，以当日收盘为基准，看未来 N 日最低价）=====')
close = wc.values; low = wl.values; atr = atr_wilder(wh,wl,wc,14).values
for N in [1,2,3,5,10]:
    row=[]
    for mult in [0.25,0.5,0.75,1.0,1.5,2.0]:
        hit=0; tot=0
        for i in range(len(w)-N):
            if np.isnan(atr[i]): continue
            d = mult*atr[i]
            fut_min = low[i+1:i+1+N].min()
            tot+=1
            if fut_min <= close[i]-d: hit+=1
        row.append('%.2fxATR:%5.1f%%'%(mult,100*hit/tot))
    print('  N=%2d  '%N + '  '.join(row))

print('\n===== 未来 1 日最大不利偏移 MAE 分布（相对当日收盘）=====')
mae = (wc.values[:-1] - wl.values[1:])/wc.values[:-1]*100
mae = pd.Series(mae)
for q in [10,25,50,75,90,95,99]:
    print('  MAE p%-2d = %.2f%%'%(q,mae.quantile(q/100)))
print('  MAE 均值 %.2f%%  最大 %.2f%%'%(mae.mean(),mae.max()))
print('  MAE > 1xATR(7.207%%) 的比例 = %.1f%%'%(100*(mae>7.207).mean()))
print('  MAE > 0.5xATR(3.60%%) 的比例 = %.1f%%'%(100*(mae>3.6035).mean()))
print('  MAE > 0.25xATR(1.80%%) 的比例 = %.1f%%'%(100*(mae>1.8018).mean()))
print('  MAE > 2xATR(14.41%%) 的比例 = %.1f%%'%(100*(mae>14.414).mean()))

# ---------- ADX ----------
upm = wh.diff(); dnm = -wl.diff()
plus_dm = pd.Series(np.where((upm>dnm)&(upm>0), upm, 0.0), index=w.index)
minus_dm = pd.Series(np.where((dnm>upm)&(dnm>0), dnm, 0.0), index=w.index)
tr = pd.concat([(wh-wl),(wh-wc.shift(1)).abs(),(wl-wc.shift(1)).abs()],axis=1).max(axis=1)
atrn = wilder_rma(tr,14)
pdi = 100*wilder_rma(plus_dm,14)/atrn
mdi = 100*wilder_rma(minus_dm,14)/atrn
dx = 100*(pdi-mdi).abs()/(pdi+mdi)
adx = wilder_rma(dx,14)
print('\n===== ADX(14) =====')
print('  +DI %.2f  -DI %.2f  ADX %.2f'%(pdi.iloc[-1],mdi.iloc[-1],adx.iloc[-1]))
print('  ADX 近 10 日: '+' '.join('%.1f'%x for x in adx.tail(10).values))
pct_rank(adx.tail(252), adx.iloc[-1], 'ADX 252')

# ---------- OBV ----------
obv = (np.sign(wc.diff())*wv).fillna(0).cumsum()
print('\n===== OBV =====')
print('  OBV 252 日起点 %.0f 末值 %.0f  区间最大 %.0f 最小 %.0f'%(obv.iloc[0],obv.iloc[-1],obv.max(),obv.min()))
print('  近 20 日 OBV 变化 %.0f；近 60 日 %.0f'%(obv.iloc[-1]-obv.iloc[-21], obv.iloc[-1]-obv.iloc[-61]))
print('  OBV 距 252 日最高点的回撤 %.2f%%'%(100*(obv.iloc[-1]-obv.max())/abs(obv.max())))
print('  OBV 近 10 日: '+' '.join('%.0f'%x for x in (obv.iloc[-1]-obv.shift(1).iloc[-1:]).values))
obv10 = obv.tail(10).values
print('  最近 10 日 OBV 序列（相对首日）: '+' '.join('%+.0f'%(x-obv10[0]) for x in obv10))

# ---------- 量能基线 ----------
print('\n===== 成交量基线 =====')
print('  20 日均量（含 10-06）%.0f'%wv.tail(20).mean())
print('  20 日均量（截至 10-01，不含三根事件 bar）%.0f'%wv.loc[:'2026-10-01'].tail(20).mean())
print('  20 日中位量 %.0f ; 60 日中位量 %.0f ; 252 日中位量 %.0f'%(wv.tail(20).median(),wv.tail(60).median(),wv.median()))
print('  60 日均量 %.0f ; 252 日均量 %.0f'%(wv.tail(60).mean(),wv.mean()))
print('  10-02 量/20日均量(截至10-01) = %.3f'% (24768500/wv.loc[:'2026-10-01'].tail(20).mean()))
print('  10-05 量/20日均量(截至10-01) = %.3f'% (11300400/wv.loc[:'2026-10-01'].tail(20).mean()))
print('  10-06 量/20日均量(截至10-01) = %.3f'% (14002200/wv.loc[:'2026-10-01'].tail(20).mean()))
print('  10-05 量 / 10-02 量 = %.4f'%(11300400/24768500))
print('  10-06 量 / 10-02 量 = %.4f'%(14002200/24768500))
print('  三根 bar 合计量 %.0f = 20日均量(8.4045M) 的 %.2f 倍'%(24768500+11300400+14002200,(24768500+11300400+14002200)/8404510))

# ---------- 三根 bar 的精细解剖 ----------
print('\n===== 三根事件 bar 解剖 =====')
for d in ['2026-10-01','2026-10-02','2026-10-05','2026-10-06']:
    r=w.loc[d]
    rng=r['High']-r['Low']
    print('  %s O %.2f H %.2f L %.2f C %.2f  量 %.0f  振幅 %.2f (%.2f%%)  实体 %.2f 上影 %.2f 下影 %.2f  close_pos %.1f%%'%(
        d,r['Open'],r['High'],r['Low'],r['Close'],r['Volume'],rng,100*rng/r['Close'],
        abs(r['Close']-r['Open']),r['High']-max(r['Close'],r['Open']),min(r['Close'],r['Open'])-r['Low'],
        100*(r['Close']-r['Low'])/rng))
print('  10-02 开盘跳空: 10-01 低 440.05 → 10-02 高 427.71，缺口 %.2f'% (440.05-427.71))
print('  10-02 自 10-01 收盘 462.56 的跌幅 %.2f%%'%(100*(415.29/462.56-1)))
print('  10-02 日内自开盘 423.20 的跌幅 %.2f%%'%(100*(415.29/423.20-1)))
print('  10-05 自 10-02 收盘 415.29 的涨幅 %.2f%%'%(100*(441.64/415.29-1)))
print('  10-06 自 10-05 收盘 441.64 的跌幅 %.2f%%'%(100*(411.04/441.64-1)))
print('  三日累计（10-01 收 462.56 → 10-06 收 411.04）%.2f%%'%(100*(411.04/462.56-1)))
print('  10-06 收 411.04 vs 10-02 收 415.29 = %.2f%%'%(100*(411.04/415.29-1)))
print('  10-06 低 406.81 vs 10-02 低 396.57 = %+.2f（%+.2f%%）'%(406.81-396.57,100*(406.81/396.57-1)))
print('  10-05 高 447.71 对 10-01高463.55→10-02低396.57 跌段的回撤比例 = %.1f%%'%(100*(447.71-396.57)/(463.55-396.57)))
print('  10-06 收 411.04 对该跌段的回撤比例 = %.1f%%'%(100*(411.04-396.57)/(463.55-396.57)))
sh=475.66; sl=396.57
print('  摆动段 09-23 高 %.2f → 10-02 低 %.2f (%.2f 点)'%(sh,sl,sh-sl))
for r_ in [0.236,0.382,0.5,0.618,0.786]:
    print('    反弹 %.1f%% = %.2f'%(r_*100, sl+(sh-sl)*r_))
print('  10-05 高 447.71 对应反弹 %.3f ; 10-06 高 430.33 对应 %.3f ; 10-06 收 411.04 对应 %.3f'%(
    (447.71-sl)/(sh-sl),(430.33-sl)/(sh-sl),(411.04-sl)/(sh-sl)))

# ---------- 结构：连续下降高点 ----------
print('\n===== 近期摆动高点序列 =====')
for d,val in [('2026-09-09',495.49),('2026-09-23',475.66),('2026-09-29',465.90),('2026-10-01',463.55),('2026-10-05',447.71),('2026-10-06',430.33)]:
    print('  %s 高 %.2f'%(d,val))
print('===== 近期摆动低点序列 =====')
for d,val in [('2026-09-15',407.12),('2026-09-28',432.04),('2026-10-02',396.57),('2026-10-06',406.81)]:
    print('  %s 低 %.2f'%(d,val))

# ---------- 回撤 ----------
print('\n===== 回撤 =====')
print('  自收盘峰值 746.23(2026-06-18) 回撤 %.2f%%'%(100*(411.04/746.23-1)))
print('  自盘中峰值 799.61 回撤 %.2f%%'%(100*(411.04/799.61-1)))
print('  自 52 周低 112.31 涨幅 %.2f%%'%(100*(411.04/112.31-1)))
print('  自 2025-10-06（252 窗口首日）收盘 %.2f 涨幅 %.2f%%'%(wc.iloc[0],100*(411.04/wc.iloc[0]-1)))
print('  252 窗口首日收盘 %.2f' % wc.iloc[0])

# ---------- 月末收盘全序列 ----------
print('\n===== 月末收盘（2025-09 ~ 2026-10）=====')
m = wc.resample('ME').last()
for d,val in m.items():
    print('  %s %.2f'%(d.strftime('%Y-%m'),val))

# ---------- 涨跌分布 ----------
print('\n===== 日收益分布（252）=====')
r=wc.pct_change().dropna()*100
for q in [1,5,10,25,50,75,90,95,99]:
    print('  p%-2d %+.2f%%'%(q,r.quantile(q/100)))
print('  均值 %+.3f%%  标准差 %.3f%%  偏度 %.3f  峰度 %.3f'%(r.mean(),r.std(),r.skew(),r.kurt()))
print('  |ret|>5%% 天数 %d (%.1f%%) ; |ret|>7%% %d ; |ret|>10%% %d'%((r.abs()>5).sum(),100*(r.abs()>5).mean(),(r.abs()>7).sum(),(r.abs()>10).sum()))
print('  下跌 >7%% 的天数 %d，其中次日上涨 %d'%((r<-7).sum(), (r.shift(-1)[r<-7]>0).sum()))

# ---------- 下跌日之后 ----------
print('\n===== 大跌日（跌幅>6%）后的表现 =====')
idx = np.where(r.values<-6)[0]
for i in idx:
    d0 = r.index[i]
    f = [wc.shift(-n).iloc[i] for n in [1,3,5]]
    print('  %s %+.2f%% → 后1 %s 后3 %s 后5 %s'%(d0.date(), r.values[i],
        '%+.2f%%'%(100*(f[0]/wc.iloc[i]-1)) if pd.notna(f[0]) else 'NA',
        '%+.2f%%'%(100*(f[1]/wc.iloc[i]-1)) if pd.notna(f[1]) else 'NA',
        '%+.2f%%'%(100*(f[2]/wc.iloc[i]-1)) if pd.notna(f[2]) else 'NA'))

# ---------- 缠论式：最近 N 日在 402-403 附近停留时间 ----------
print('\n===== 400~410 区间的历史成交密集度 =====')
tp=(wh+wl+wc)/3
for a,b in [(396,406),(400,410),(402,404),(406,416),(410,420),(420,430),(430,440),(440,450),(450,460),(460,470)]:
    sel=(tp>=a)&(tp<b)
    print('  [%d,%d) : %d 根，占 %.1f%%，累计量 %.0f (%.2f%%)，累计量/日 %.0f'%(
        a,b,sel.sum(),100*sel.mean(),wv[sel].sum(),100*wv[sel].sum()/wv.sum(), wv[sel].sum()/max(sel.sum(),1)))

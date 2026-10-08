# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第三轮：缺口核验、波动挤压序列、MACD 死叉历史、200SMA 长样本分位。"""
import numpy as np, pandas as pd, yfinance as yf

END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2023-06-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()
def wilder_rma(s,n): return s.ewm(alpha=1.0/n, adjust=False).mean()
def atr_wilder(h,l,c,n=14):
    pc=c.shift(1); tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); return wilder_rma(tr,n)
c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']

print('rows', len(df), df.index.min().date(), df.index.max().date())

# ===== 缺口核验 =====
print('\n===== 2026-04-24 ~ 2026-05-06 原始 bar =====')
print(df.loc['2026-04-24':'2026-05-06'].to_string(float_format=lambda x:'%.2f'%x))
print('\n252 窗口最低 low = %.2f @ %s' % (df['Low'].tail(252).min(), df['Low'].tail(252).idxmin().date()))
print('2026-04-28 high = %.2f ; 距 10-02 低 396.57 仅 %.2f' % (df.loc['2026-04-28','High'], df.loc['2026-04-28','High']-396.57))
print('\n===== 2026-06-29 ~ 2026-07-03 原始 bar（未回补下跳空）=====')
print(df.loc['2026-06-29':'2026-07-03'].to_string(float_format=lambda x:'%.2f'%x))
print('  该缺口上沿 630.30，其后最高 high = %.2f @ %s' % (df.loc['2026-07-01':,'High'].max(), df.loc['2026-07-01':,'High'].idxmax().date()))

# ===== 波动挤压序列 =====
w = df.tail(252).copy()
wc,wh,wl,wv = w['Close'],w['High'],w['Low'],w['Volume']
mid = wc.rolling(20).mean(); sd = wc.rolling(20).std(ddof=1)
bw = 4*sd/mid*100
atr14 = atr_wilder(wh,wl,wc,14); atrp = atr14/wc*100
out = pd.DataFrame({'close':wc,'bw%':bw,'atr%':atrp,'vol':wv}).tail(45)
print('\n===== 近 45 根 带宽%% / ATR%% =====')
print(out.to_string(float_format=lambda x:'%.2f'%x))
print('\n  bw%% 20 日窗口 min %.3f 出现在 %s' % (bw.tail(20).min(), bw.tail(20).idxmin().date()))
print('  bw%% 60 日窗口 min %.3f 出现在 %s' % (bw.tail(60).min(), bw.tail(60).idxmin().date()))
print('  atr%% 20 日窗口 min %.3f 出现在 %s' % (atrp.tail(20).min(), atrp.tail(20).idxmin().date()))

# ===== MACD 死叉历史统计 =====
ema12=c.ewm(span=12,adjust=False).mean(); ema26=c.ewm(span=26,adjust=False).mean()
macd=ema12-ema26; sig=macd.ewm(span=9,adjust=False).mean(); hist=macd-sig
print('\n===== MACD hist 日变化噪声 =====')
dh = hist.diff()
for n in [10,20,60,120,252]:
    print('  Δhist 标准差(%d) = %.3f ; 均值 %.3f' % (n, dh.tail(n).std(), dh.tail(n).mean()))
print('  最近 10 日 Δhist: ' + ' '.join('%+.3f'%x for x in dh.tail(10).values))
print('  |当前 hist| %.3f / Δhist 标准差(20) %.3f = %.2f 倍' % (abs(hist.iloc[-1]), dh.tail(20).std(), abs(hist.iloc[-1])/dh.tail(20).std()))
print('  |当前 hist| %.3f / Δhist 标准差(60) %.3f = %.2f 倍' % (abs(hist.iloc[-1]), dh.tail(60).std(), abs(hist.iloc[-1])/dh.tail(60).std()))
print('  hist 近 20 日的区间: %.3f ~ %.3f' % (hist.tail(20).min(), hist.tail(20).max()))
print('  hist 近 60 日的区间: %.3f ~ %.3f' % (hist.tail(60).min(), hist.tail(60).max()))
print('  hist 近 252 日的区间: %.3f ~ %.3f' % (hist.tail(252).min(), hist.tail(252).max()))

# 死叉后续
w_macd = hist.tail(252); w_close = c.tail(252)
print('\n===== 252 窗口内 macdh 由正翻负后的前向收益 =====')
rows=[]
vals = w_macd.values; cl = w_close.values; idx = w_macd.index
for i in range(1,len(vals)):
    if vals[i-1]>0 and vals[i]<0 and i < len(vals)-1:
        f5 = (cl[i+5]/cl[i]-1)*100 if i+5 < len(cl) else np.nan
        f10 = (cl[i+10]/cl[i]-1)*100 if i+10 < len(cl) else np.nan
        f3 = (cl[i+3]/cl[i]-1)*100 if i+3 < len(cl) else np.nan
        f1 = (cl[i+1]/cl[i]-1)*100 if i+1 < len(cl) else np.nan
        rows.append((idx[i].date(), vals[i-1], vals[i], f1,f3,f5,f10))
for r in rows:
    print('  %s  %+.3f→%+.3f | 1d %s 3d %s 5d %s 10d %s'%(r[0],r[1],r[2],
      '%+.2f%%'%r[3] if pd.notna(r[3]) else 'NA','%+.2f%%'%r[4] if pd.notna(r[4]) else 'NA',
      '%+.2f%%'%r[5] if pd.notna(r[5]) else 'NA','%+.2f%%'%r[6] if pd.notna(r[6]) else 'NA'))
f5v=[r[5] for r in rows if pd.notna(r[5])]
print('  5 日前向收益：n=%d 正 %d 负 %d 中位 %+.2f%% 均值 %+.2f%%'%(len(f5v),sum(1 for x in f5v if x>0),sum(1 for x in f5v if x<0),np.median(f5v),np.mean(f5v)))
f10v=[r[6] for r in rows if pd.notna(r[6])]
print('  10 日前向收益：n=%d 正 %d 负 %d 中位 %+.2f%%'%(len(f10v),sum(1 for x in f10v if x>0),sum(1 for x in f10v if x<0),np.median(f10v)))

# ===== 200SMA 长样本 =====
s200 = c.rolling(200).mean(); s50 = c.rolling(50).mean()
d200 = (c/s200-1)*100
sub = d200.dropna()
print('\n===== 距 200SMA 百分比（全样本 n=%d，%s ~ %s）=====' % (len(sub), sub.index.min().date(), sub.index.max().date()))
print('  当前 %+.3f%%  rank %.2f%%' % (d200.iloc[-1], 100*(sub < d200.iloc[-1]).sum()/len(sub)))
for q in [1,5,10,25,50,75]:
    print('  p%-2d %+.2f%%'%(q, sub.quantile(q/100)))
print('  小于 5%% 的天数 %d (%.1f%%)' % ((sub<5).sum(), 100*(sub<5).mean()))
print('  小于 3%% 的天数 %d (%.1f%%)' % ((sub<3).sum(), 100*(sub<3).mean()))
print('  这些 <5%% 的日期: ' + ', '.join(str(d.date()) for d in sub[sub<5].index[-25:]))
print('  连续在 200SMA 上方天数（全样本末日倒推）:')
cnt=0
for x in (c>s200).dropna().values[::-1]:
    if x: cnt+=1
    else: break
print('   %d 根' % cnt)
print('  首次站上并持续在 200SMA 之上的起点日期:')
above = (c>s200).dropna()
first = above.index[np.where(~above.values[:-1] & above.values[1:])[0][-1]+1]
print('   %s（此后连续 %d 根在上方）' % (first.date(), len(above)-above.index.get_loc(first)))

# ===== 50SMA 长样本 =====
d50 = (c/s50-1)*100
sub50 = d50.dropna()
print('\n===== 距 50SMA 百分比（全样本 n=%d）=====' % len(sub50))
print('  当前 %+.3f%%  rank %.2f%%' % (d50.iloc[-1], 100*(sub50 < d50.iloc[-1]).sum()/len(sub50)))
print('  连续在 50SMA 下方天数:')
cnt=0
for x in (c<s50).dropna().values[::-1]:
    if x: cnt+=1
    else: break
print('   %d 根' % cnt)
print('  历史（近 3 年）连续在 50SMA 下方的最长纪录:')
below=(c<s50).dropna()
runs=[]; cur=0
for x in below.values:
    if x: cur+=1
    else:
        if cur: runs.append(cur); cur=0
if cur: runs.append(cur)
print('   最长 %d 根，前五长 %s' % (max(runs), sorted(runs, reverse=True)[:5]))

# ===== ATR%% 更长样本 =====
atrp_full = atr_wilder(h,l,c,14)/c*100
print('\n===== ATR%% 更长样本 =====')
for n in [252, 500, len(df)]:
    s=atrp_full.dropna().tail(n)
    print('  n=%3d: 当前 %.3f rank %.1f%% | p10 %.2f p25 %.2f med %.2f p75 %.2f p90 %.2f max %.2f'%(
        len(s), atrp_full.iloc[-1], 100*(s<atrp_full.iloc[-1]).sum()/len(s), s.quantile(.1),s.quantile(.25),s.median(),s.quantile(.75),s.quantile(.9),s.max()))

# ===== 整数关口与关键位附近历史换手 =====
print('\n===== 关键价位附近的历史换手（252 根，按典型价 5 美元一档，覆盖 380~500）=====')
tp=(wh+wl+wc)/3
for a in range(380,500,5):
    sel=(tp>=a)&(tp<a+5)
    if sel.sum()==0: 
        print('  [%d,%d) 0 根'%(a,a+5)); continue
    print('  [%d,%d) %2d 根 量 %10.0f (%.2f%%) 日均量 %8.0f'%(a,a+5,sel.sum(),wv[sel].sum(),100*wv[sel].sum()/wv.sum(),wv[sel].sum()/sel.sum()))

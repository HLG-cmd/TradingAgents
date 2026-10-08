# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""复算 WDC 口径 A（止于 2026-10-06）技术指标 + 量价分布统计。
只用于 wdc-mkt-r1 撰写 market.md 前的自算，不写任何分析文件。
"""
import numpy as np
import pandas as pd
import yfinance as yf
import json

END = pd.Timestamp('2026-10-06')

df = yf.download('WDC', start='2024-01-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
df = df[df.index <= END].copy()

print('full rows:', len(df), 'range:', df.index.min().date(), df.index.max().date())

# ---------- 指标 ----------
def wilder_rma(s, n):
    return s.ewm(alpha=1.0/n, adjust=False).mean()

def rsi_wilder(close, n=14):
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = wilder_rma(up, n)
    rd = wilder_rma(dn, n)
    return 100 - 100/(1 + ru/rd)

def atr_wilder(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return wilder_rma(tr, n)

c, h, l, v = df['Close'], df['High'], df['Low'], df['Volume']

df['sma50'] = c.rolling(50).mean()
df['sma200'] = c.rolling(200).mean()
df['ema10'] = c.ewm(span=10, adjust=False).mean()
df['ema12'] = c.ewm(span=12, adjust=False).mean()
df['ema26'] = c.ewm(span=26, adjust=False).mean()
df['macd'] = df['ema12'] - df['ema26']
df['macds'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macdh'] = df['macd'] - df['macds']
df['rsi14'] = rsi_wilder(c, 14)
df['atr14'] = atr_wilder(h, l, c, 14)
df['boll_mid'] = c.rolling(20).mean()
sd_pop = c.rolling(20).std(ddof=0)
sd_smp = c.rolling(20).std(ddof=1)
df['boll_ub_pop'] = df['boll_mid'] + 2*sd_pop
df['boll_lb_pop'] = df['boll_mid'] - 2*sd_pop
df['boll_ub_smp'] = df['boll_mid'] + 2*sd_smp
df['boll_lb_smp'] = df['boll_mid'] - 2*sd_smp
# vwma 20
tp = (h + l + c)/3
df['vwma20'] = (tp*v).rolling(20).sum()/v.rolling(20).sum()
df['vwma_v1'] = (c*v).rolling(20).sum()/v.rolling(20).sum()

print('\n===== 复算对齐检查（末 5 根）=====')
cols = ['Close','sma50','sma200','ema10','macd','macds','macdh','rsi14','atr14','boll_mid',
        'boll_ub_pop','boll_lb_pop','boll_ub_smp','boll_lb_smp','vwma20','vwma_v1','Volume']
print(df[cols].tail(5).to_string())

# ---------- 252 根窗口 ----------
w = df.tail(252).copy()
print('\n252 窗口:', w.index.min().date(), '~', w.index.max().date(), len(w))
wc, wh, wl, wv = w['Close'], w['High'], w['Low'], w['Volume']

# 收益 / 波动
w['ret'] = wc.pct_change()*100
w['tr'] = pd.concat([(wh-wl), (wh-wc.shift(1)).abs(), (wl-wc.shift(1)).abs()], axis=1).max(axis=1)
w['tr_pct'] = w['tr']/wc*100
w['range_pct'] = (wh-wl)/wc*100
w['close_pos'] = (wc-wl)/(wh-wl)*100
w['atr_pct'] = w['atr14']/wc*100
w['bw_pct'] = (w['boll_ub_pop']-w['boll_lb_pop'])/w['boll_mid']*100
w['vol20'] = wv.rolling(20).mean()
w['vr'] = wv/w['vol20']

last = w.iloc[-1]
print('\n===== 关键当前值 =====')
print('close %.2f  atr %.4f  atr%% %.4f  bw%% %.4f' % (last['Close'], last['atr14'], last['atr_pct'], last['bw_pct']))
print('rsi %.4f  macd %.4f signal %.4f hist %.4f' % (last['rsi14'], last['macd'], last['macds'], last['macdh']))

def pct_rank(series, value, label):
    s = series.dropna()
    below = (s < value).sum()
    print('%-28s n=%3d  value=%8.3f  rank=%.1f%% (min %.3f / p25 %.3f / median %.3f / p75 %.3f / p90 %.3f / max %.3f / mean %.3f)' % (
        label, len(s), value, 100*below/len(s), s.min(), s.quantile(.25), s.median(), s.quantile(.75), s.quantile(.90), s.max(), s.mean()))

print('\n===== ATR%% 分位 =====')
pct_rank(w['atr_pct'].tail(252), last['atr_pct'], 'ATR% 252')
pct_rank(w['atr_pct'].tail(120), last['atr_pct'], 'ATR% 120')
pct_rank(w['atr_pct'].tail(60), last['atr_pct'], 'ATR% 60')
pct_rank(w['atr_pct'].tail(20), last['atr_pct'], 'ATR% 20')

print('\n===== 布林带宽%% 分位 =====')
pct_rank(w['bw_pct'].tail(252), last['bw_pct'], 'BW% 252')
pct_rank(w['bw_pct'].tail(120), last['bw_pct'], 'BW% 120')
pct_rank(w['bw_pct'].tail(60), last['bw_pct'], 'BW% 60')

print('\n===== RSI 分位 =====')
pct_rank(w['rsi14'].tail(252), last['rsi14'], 'RSI 252')
pct_rank(w['rsi14'].tail(120), last['rsi14'], 'RSI 120')
for thr in [20, 25, 30, 35, 40, 45, 50, 70]:
    print('  RSI<%d 天数(252) = %d (%.1f%%)' % (thr, (w['rsi14']<thr).sum(), 100*(w['rsi14']<thr).sum()/len(w)))
print('  RSI 最小值 %.2f 出现在 %s' % (w['rsi14'].min(), w['rsi14'].idxmin().date()))

print('\n===== 日真实波幅 TR%% 分布 =====')
pct_rank(w['tr_pct'], last['tr']/last['Close']*100, 'TR% 252')
print('\n  close_pos 分布: p10 %.1f p25 %.1f median %.1f p75 %.1f' % (w['close_pos'].quantile(.1), w['close_pos'].quantile(.25), w['close_pos'].median(), w['close_pos'].quantile(.75)))
print('  close_pos<20 的天数 = %d (%.1f%%)' % ((w['close_pos']<20).sum(), 100*(w['close_pos']<20).sum()/len(w)))
print('  close_pos<10 的天数 = %d (%.1f%%)' % ((w['close_pos']<10).sum(), 100*(w['close_pos']<10).sum()/len(w)))

print('\n===== 量能 =====')
print('20 日均量 %.0f' % last['vol20'])
print('量比分位:')
pct_rank(w['vr'], last['vr'], 'VR 252')
for thr in [1.0,1.2,1.5,2.0,2.5,3.0]:
    print('  VR>%.1f 天数 = %d (%.1f%%)' % (thr, (w['vr']>thr).sum(), 100*(w['vr']>thr).sum()/len(w.dropna(subset=['vr']))))
# 涨跌日量
w['dir'] = np.sign(wc.diff())
print('  上涨日均量 %.0f / 下跌日均量 %.0f  比值 %.3f' % (
    wv[w['dir']>0].mean(), wv[w['dir']<0].mean(), wv[w['dir']>0].mean()/wv[w['dir']<0].mean()))
print('  上涨日量(中位) %.0f / 下跌日量(中位) %.0f' % (wv[w['dir']>0].median(), wv[w['dir']<0].median()))
print('  下跌日且 close_pos<25 的天数量比均值 %.2f' % w['vr'][(w['dir']<0)&(w['close_pos']<25)].mean())

print('\n===== 最近 20 根明细 =====')
print(w[['Open','High','Low','Close','Volume','ret','close_pos','vr','atr_pct','bw_pct','rsi14','macdh']].tail(20).to_string(float_format=lambda x: '%.2f'%x))

# ---------- 成交量价格分布 (volume-by-price) ----------
print('\n===== 成交量价格分布（252 根，10 美元一档）=====')
lo = float(wl.min()); hi = float(wh.max())
bins = np.arange(np.floor(lo/10)*10, np.ceil(hi/10)*10+10, 10)
w['bin'] = pd.cut(((wh+wl+wc)/3), bins)
prof = w.groupby('bin', observed=True)['Volume'].sum().sort_values(ascending=False)
tot = prof.sum()
for b, val in prof.head(15).items():
    print('  %s  vol=%12.0f  %.2f%%' % (str(b), val, 100*val/tot))

print('\n===== 成交量价格分布（120 根，10 美元一档）=====')
w2 = w.tail(120)
bins2 = np.arange(np.floor(w2['Low'].min()/10)*10, np.ceil(w2['High'].max()/10)*10+10, 10)
w2 = w2.copy()
w2['bin'] = pd.cut(((w2['High']+w2['Low']+w2['Close'])/3), bins2)
prof2 = w2.groupby('bin', observed=True)['Volume'].sum().sort_values(ascending=False)
tot2 = prof2.sum()
for b, val in prof2.head(12).items():
    print('  %s  vol=%12.0f  %.2f%%' % (str(b), val, 100*val/tot2))

# ---------- VWAP 能级 ----------
print('\n===== 各窗口 VWAP（典型价加权）=====')
tpw = (wh+wl+wc)/3
for n in [5, 10, 20, 50, 60, 120, 252]:
    vw = (tpw*wv).rolling(n).sum()/wv.rolling(n).sum()
    print('  VWAP%3d = %.2f  (距现价 %+.2f%%)' % (n, vw.iloc[-1], 100*(411.04/vw.iloc[-1]-1)))

print('\n===== 自峰值以来 VWAP =====')
peak_idx = wc.idxmax()
print('  252 窗口内收盘峰值 %.2f @ %s' % (wc.max(), peak_idx.date()))
seg = w.loc[peak_idx:]
vwp = (tpw*wv).loc[peak_idx:].sum()/wv.loc[peak_idx:].sum()
print('  峰值以来 VWAP = %.2f（%d 根）' % (vwp, len(seg)))

# 全历史（更长窗口）峰值
print('\n  更长窗口峰值:')
long_c = c.loc['2026-06-01':'2026-07-31']
print('   2026-06~07 收盘最高 %.2f @ %s' % (long_c.max(), long_c.idxmax().date()))
pk2 = long_c.idxmax()
seg2 = df.loc[pk2:]
tp2 = (df['High']+df['Low']+df['Close'])/3
vwp2 = (tp2*df['Volume']).loc[pk2:].sum()/df['Volume'].loc[pk2:].sum()
print('   峰值以来 VWAP = %.2f（%d 根，%s ~ %s）' % (vwp2, len(seg2), pk2.date(), df.index.max().date()))

seg3 = df.loc['2026-09-01':]
vwp3 = (tp2*df['Volume']).loc['2026-09-01':].sum()/df['Volume'].loc['2026-09-01':].sum()
print('   9 月以来 VWAP = %.2f（%d 根）' % (vwp3, len(seg3)))

# ---------- 缺口 ----------
print('\n===== 缺口扫描（近 120 根，幅度>1 美元且未回补）=====')
hh = w['High'].values; ll = w['Low'].values; idx = w.index
for i in range(len(w)-120, len(w)):
    # 向下缺口: 今日 high < 昨日 low
    if hh[i] < ll[i-1] and (ll[i-1]-hh[i]) > 1:
        filled = False
        for j in range(i+1, len(w)):
            if hh[j] >= ll[i-1]:
                filled = True; break
        print('  向下缺口 %s: %.2f -> %.2f (gap %.2f)  %s' % (idx[i].date(), ll[i-1], hh[i], ll[i-1]-hh[i], '已回补' if filled else '★未回补'))
    # 向上缺口
    if ll[i] > hh[i-1] and (ll[i]-hh[i-1]) > 1:
        filled = False
        for j in range(i+1, len(w)):
            if ll[j] <= hh[i-1]:
                filled = True; break
        print('  向上缺口 %s: %.2f -> %.2f (gap %.2f)  %s' % (idx[i].date(), hh[i-1], ll[i], ll[i]-hh[i-1], '已回补' if filled else '★未回补'))

# ---------- 摆动高低点 ----------
print('\n===== 摆动高低点（fractal 5）=====')
k = 2
sw = []
for i in range(k, len(w)-k):
    hi_win = wh.iloc[i-k:i+k+1]
    lo_win = wl.iloc[i-k:i+k+1]
    if wh.iloc[i] == hi_win.max():
        sw.append((w.index[i].date(), 'H', float(wh.iloc[i])))
    if wl.iloc[i] == lo_win.min():
        sw.append((w.index[i].date(), 'L', float(wl.iloc[i])))
for s in sw[-24:]:
    print('  %s %s %.2f' % s)

# ---------- 斐波那契 ----------
print('\n===== 斐波那契（峰值收盘 746.23 -> 近期低点）=====')
recent_low = wl.loc['2026-10-01':].min()
print('  10 月以来最低 %.2f' % recent_low)
P = 746.23
for r in [0.236, 0.382, 0.5, 0.618, 0.786]:
    print('   回撤 %.1f%%: %.2f' % (r*100, P - (P-recent_low)*r))
print('  52周高 799.61 -> 52周低 112.31:')
for r in [0.382, 0.5, 0.618]:
    print('   回撤 %.1f%%: %.2f' % (r*100, 799.61 - (799.61-112.31)*r))

# ---------- 月末收盘 ----------
print('\n===== 月末收盘序列 =====')
m = wc.resample('ME').last()
print(m.to_string())

# ---------- 历史类比：MACD hist 由正翻负 ----------
print('\n===== 历史类比：macdh 由正翻负（252 窗口内）=====')
mh = w['macdh']
for i in range(1, len(w)):
    if mh.iloc[i-1] > 0 and mh.iloc[i] < 0:
        d0 = w.index[i]
        fwd = [wc.shift(-n).iloc[i] for n in [1,3,5,10,20]]
        print('  %s hist %.3f -> %.3f | 后1日 %s 后3日 %s 后5日 %s 后10日 %s 后20日 %s' % (
            d0.date(), mh.iloc[i-1], mh.iloc[i],
            '%.2f%%'%((fwd[0]/wc.iloc[i]-1)*100) if pd.notna(fwd[0]) else 'NA',
            '%.2f%%'%((fwd[1]/wc.iloc[i]-1)*100) if pd.notna(fwd[1]) else 'NA',
            '%.2f%%'%((fwd[2]/wc.iloc[i]-1)*100) if pd.notna(fwd[2]) else 'NA',
            '%.2f%%'%((fwd[3]/wc.iloc[i]-1)*100) if pd.notna(fwd[3]) else 'NA',
            '%.2f%%'%((fwd[4]/wc.iloc[i]-1)*100) if pd.notna(fwd[4]) else 'NA'))

print('\n===== 历史类比：收盘价位于日内 18% 以下且量比>1.5 的下跌日 =====')
cond = (w['close_pos']<20)&(w['vr']>1.5)&(w['dir']<0)
for i in np.where(cond)[0]:
    d0 = w.index[i]
    fwd = [wc.shift(-n).iloc[i] for n in [1,3,5,10]]
    print('  %s 收 %.2f (%+.2f%%) close_pos %.1f vr %.2f | 后1 %s 后3 %s 后5 %s 后10 %s' % (
        d0.date(), wc.iloc[i], w['ret'].iloc[i], w['close_pos'].iloc[i], w['vr'].iloc[i],
        '%.2f%%'%((fwd[0]/wc.iloc[i]-1)*100) if pd.notna(fwd[0]) else 'NA',
        '%.2f%%'%((fwd[1]/wc.iloc[i]-1)*100) if pd.notna(fwd[1]) else 'NA',
        '%.2f%%'%((fwd[2]/wc.iloc[i]-1)*100) if pd.notna(fwd[2]) else 'NA',
        '%.2f%%'%((fwd[3]/wc.iloc[i]-1)*100) if pd.notna(fwd[3]) else 'NA'))

# ---------- 已实现波动率 ----------
print('\n===== 已实现波动率 =====')
for n in [5, 10, 20, 60, 120, 252]:
    rv = w['ret'].tail(n).std(ddof=1)*np.sqrt(252)
    print('  %3d 日年化已实现波动率 %.2f%%  (日 %.2f%%)' % (n, rv, rv/np.sqrt(252)))
print('  ATR%% 7.207 对应的"等价日波动": 若日收益标准差≈ATR%%/1.5~2.0 → %.2f%%~%.2f%% → 年化 %.0f%%~%.0f%%' % (
    7.207/2.0, 7.207/1.5, 7.207/2.0*np.sqrt(252), 7.207/1.5*np.sqrt(252)))

# ---------- 连续跌破 ----------
print('\n===== 价格与 50SMA / 200SMA 的关系 =====')
w['above50'] = wc > w['sma50']
w['above200'] = wc > w['sma200']
print('  连续在 50SMA 下方的天数（至末日）:')
cnt=0
for x in w['above50'].values[::-1]:
    if not x: cnt+=1
    else: break
print('   %d 根' % cnt)
cnt=0
for x in w['above200'].values[::-1]:
    if x: cnt+=1
    else: break
print('  连续在 200SMA 上方的天数: %d 根' % cnt)
print('  252 窗口中收盘在 200SMA 上方的比例 %.1f%%' % (100*w['above200'].mean()))
print('  252 窗口中收盘在 50SMA 上方的比例 %.1f%%' % (100*w['above50'].mean()))
# 首次跌破 50SMA 的日期
brk = w[(~w['above50']) & (w['above50'].shift(1))]
print('  最近一次由上方跌破 50SMA: %s' % (brk.index[-1].date() if len(brk) else 'NA'))

# 50SMA 与 200SMA 距离
print('  50SMA-200SMA 差 %.2f (%.2f%%)；历史 60 日的差值序列:' % (last['sma50']-last['sma200'], 100*(last['sma50']/last['sma200']-1)))
sp = (w['sma50']-w['sma200']).tail(60)
print('   60 日内最小 %.2f 最大 %.2f 中位 %.2f 当前 %.2f' % (sp.min(), sp.max(), sp.median(), sp.iloc[-1]))

# ---------- 距离关键位 ----------
print('\n===== 现价到各关键位（口径 A 411.04）=====')
levels = {'200SMA':402.39,'boll_lb':403.09,'10EMA':439.82,'VWMA20':438.29,'boll_mid':444.84,
          '50SMA':462.77,'boll_ub':486.59,'VWAP20':None}
for k, val in levels.items():
    if val is None: continue
    print('  %-8s %.2f  距离 %+.2f (%.2f%%)  = %.2f×ATR' % (k, val, 411.04-val, 100*(411.04/val-1), abs(411.04-val)/29.62))

# ---------- 200SMA 未来轨迹（若斜率维持）----------
print('\n===== 200SMA 未来外推（斜率 +1.30/日，注意 200SMA 每日变化 = (新值-剔除值)/200）=====')
for d in [1,3,5,10,20]:
    print('  +%2d 交易日 → 约 %.2f' % (d, 402.39 + 1.30*d))
# 精确：用滚动窗口外推
print('  精确外推（假设未来每日收盘 = 411.04 不变）:')
sim = df['Close'].copy()
for d in [1,3,5,10,20]:
    s = pd.concat([df['Close'], pd.Series([411.04]*d)])
    print('   +%2d 日 → 200SMA ≈ %.2f' % (d, s.rolling(200).mean().iloc[-1]))

print('\n===== 50SMA 精确外推（假设未来收盘持平 411.04）=====')
for d in [1,3,5,10,20]:
    s = pd.concat([df['Close'], pd.Series([411.04]*d)])
    print('   +%2d 日 → 50SMA ≈ %.2f' % (d, s.rolling(50).mean().iloc[-1]))

w.to_csv(r'D:\Antigravity\TradingAgents\scripts\_wdc_mkt_windows.csv')
print('\nsaved csv')

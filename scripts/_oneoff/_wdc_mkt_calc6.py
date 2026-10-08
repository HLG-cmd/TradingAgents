# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第六轮：通道/趋势线、均值回归速度、Keltner/ATR通道、波动率锥、量价相关、周线、枢轴点。"""
import numpy as np, pandas as pd, yfinance as yf
END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2023-06-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()
c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']
def rma(s,n): return s.ewm(alpha=1.0/n, adjust=False).mean()
def atr_w(hh,ll,cc,n=14):
    pc=cc.shift(1); tr=pd.concat([(hh-ll),(hh-pc).abs(),(ll-pc).abs()],axis=1).max(axis=1); return rma(tr,n)
w = df.tail(252).copy(); wc,wh,wl,wv = w['Close'],w['High'],w['Low'],w['Volume']

# ===== 1. 下降通道 =====
print('===== 下降通道（用摆动高点拟合上轨，平行下轨过摆动低点）=====')
hi_pts = [('2026-09-09',495.49),('2026-09-23',475.66),('2026-09-29',465.90),('2026-10-01',463.55),('2026-10-05',447.71),('2026-10-06',430.33)]
idx = pd.to_datetime([p[0] for p in hi_pts]); x = np.arange(len(hi_pts)); y=np.array([p[1] for p in hi_pts])
b = np.polyfit(x,y,1)
print('  上轨拟合: slope %.3f 点/摆动 ; 截距 %.2f' % (b[0], b[1]))
print('  摆动间隔（交易日）: ' + ' '.join(str(int((idx[i+1]-idx[i]).days)) for i in range(len(idx)-1)))
# 用日期为 x 重拟合
xd = np.array([ (d - idx[0]).days for d in idx ], dtype=float)
b2 = np.polyfit(xd,y,1)
print('  按自然日: slope %.4f 点/日 -> 交易日约 %.3f 点/交易日' % (b2[0], b2[0]*7/5))
# 上轨外推到 10-06
d_last = (pd.Timestamp('2026-10-06') - idx[0]).days
upper_now = np.polyval(b2, d_last)
print('  上轨在 2026-10-06 的值 = %.2f （当日实际高 430.33）' % upper_now)
# 下轨: 平行线过 10-02 低 396.57
d_low = (pd.Timestamp('2026-10-02') - idx[0]).days
lower_1002 = 396.57
off = lower_1002 - np.polyval(b2, d_low)
print('  下轨（平行、过 10-02 低 396.57）偏移 = %.2f' % off)
print('  下轨在 2026-10-06 = %.2f ; 在 +5 交易日 = %.2f ; 在 +10 交易日 = %.2f' % (
    np.polyval(b2,d_last)+off, np.polyval(b2,d_last+7)+off, np.polyval(b2,d_last+14)+off))
print('  上轨在 +5 交易日 = %.2f ; 在 +10 交易日 = %.2f' % (np.polyval(b2,d_last+7), np.polyval(b2,d_last+14)))
print('  通道宽度 = %.2f 点 = %.2f×ATR(29.62)' % (-off, -off/29.62))

# ===== 2. 均值回归速度：距 50SMA < -10% 之后 =====
s50 = c.rolling(50).mean(); d50=(c/s50-1)*100
print('\n===== 收盘距 50SMA < -10%% 之后的前向表现（全样本）=====')
cond = d50 < -10
rows=[]
for i in np.where(cond.values)[0]:
    if i+20 >= len(c): continue
    rows.append((c.index[i].date(), d50.values[i], c.values[i],
        (c.values[i+5]/c.values[i]-1)*100,(c.values[i+10]/c.values[i]-1)*100,(c.values[i+20]/c.values[i]-1)*100))
for r in rows:
    print('  %s d50 %.2f%% close %.2f | 5d %+.2f%% 10d %+.2f%% 20d %+.2f%%' % r)
f5=[r[3] for r in rows]; f10=[r[4] for r in rows]; f20=[r[5] for r in rows]
print('  n=%d | 5d 中位 %+.2f%% 胜率 %.1f%% | 10d 中位 %+.2f%% 胜率 %.1f%% | 20d 中位 %+.2f%% 胜率 %.1f%%'%(
 len(f5),np.median(f5),100*np.mean(np.array(f5)>0),np.median(f10),100*np.mean(np.array(f10)>0),
 np.median(f20),100*np.mean(np.array(f20)>0)))
# 回归到 50SMA 的时间
print('\n===== 距 50SMA < -10% 后，首次重新站上 50SMA 所需交易日 =====')
cnt=0; tot=[]
for i in np.where(cond.values)[0]:
    for j in range(1,61):
        if i+j>=len(c): break
        if c.values[i+j] > s50.values[i+j]:
            tot.append(j); break
if tot: print('  n=%d 中位 %d 日 均值 %.1f 日 最长 %d 日'%(len(tot),int(np.median(tot)),np.mean(tot),max(tot)))

# ===== 3. Keltner 与 ATR 通道 =====
atr = atr_w(wh,wl,wc,14); ema20 = wc.ewm(span=20,adjust=False).mean()
print('\n===== Keltner(20EMA ± 2×ATR) 与 ATR 通道 =====')
print('  20EMA %.2f ; ATR %.2f' % (ema20.iloc[-1], atr.iloc[-1]))
print('  Keltner 上轨 %.2f / 下轨 %.2f（距现价 %+.2f%% / %+.2f%%）'%(
 ema20.iloc[-1]+2*atr.iloc[-1], ema20.iloc[-1]-2*atr.iloc[-1],
 100*((ema20.iloc[-1]+2*atr.iloc[-1])/411.04-1), 100*((ema20.iloc[-1]-2*atr.iloc[-1])/411.04-1)))
print('  1×ATR 通道: %.2f ~ %.2f' % (ema20.iloc[-1]-atr.iloc[-1], ema20.iloc[-1]+atr.iloc[-1]))
print('  现价 411.04 在 Keltner 通道中的位置 = %.1f%%'%(100*(411.04-(ema20.iloc[-1]-2*atr.iloc[-1]))/(4*atr.iloc[-1])))
# ATR 跟踪止损（自 9 月高点起的最高收盘 - 3*ATR）
print('  ATR 跟踪止损（3×ATR，自最高收盘 746.23 起）: %.2f' % (746.23 - 3*atr.iloc[-1]))
hh = wc.rolling(20).max()
print('  20 日最高收盘 %.2f - 2×ATR = %.2f ; -3×ATR = %.2f'%(hh.iloc[-1], hh.iloc[-1]-2*atr.iloc[-1], hh.iloc[-1]-3*atr.iloc[-1]))

# ===== 4. 波动率锥 =====
print('\n===== 波动率锥：N 日内最大不利偏移（MAE）与最大有利偏移（MFE）=====')
print('  %-6s %-10s %-10s %-10s %-10s %-10s'%('N','MAE中位','MAE p75','MAE p90','MFE中位','MFE p90'))
for N in [1,2,3,5,10,20]:
    mae=[]; mfe=[]
    for i in range(len(w)-N):
        fut_l = wl.values[i+1:i+1+N].min(); fut_h = wh.values[i+1:i+1+N].max()
        mae.append((fut_l/wc.values[i]-1)*100); mfe.append((fut_h/wc.values[i]-1)*100)
    mae=np.array(mae); mfe=np.array(mfe)
    print('  %-6d %-10.2f %-10.2f %-10.2f %-10.2f %-10.2f'%(N,np.median(mae),np.percentile(mae,75),np.percentile(mae,90),np.median(mfe),np.percentile(mfe,90)))
print('\n===== N 日累计收益的绝对值分布 =====')
for N in [1,3,5,10,20]:
    r = (wc.shift(-N)/wc - 1).dropna()*100
    print('  N=%2d: |ret| 中位 %.2f%% p75 %.2f%% p90 %.2f%% p95 %.2f%% max %.2f%%'%(
        N, r.abs().median(), r.abs().quantile(.75), r.abs().quantile(.90), r.abs().quantile(.95), r.abs().max()))

# ===== 5. 量价相关性 =====
print('\n===== 量价关系（252 窗口）=====')
rng = (wh-wl)/wc*100; ret=wc.pct_change()*100; vol=wv
print('  corr(成交量, 振幅%%) = %.3f'%np.corrcoef(vol[1:], rng[1:])[0,1])
print('  corr(成交量, |日收益|) = %.3f'%np.corrcoef(vol[1:], ret.abs()[1:])[0,1])
print('  corr(量比, |日收益|) = %.3f'%np.corrcoef((vol/vol.rolling(20).mean())[1:], ret.abs()[1:])[0,1])
print('  corr(量比, 日收益) = %.3f'%np.corrcoef((vol/vol.rolling(20).mean())[1:], ret[1:])[0,1])
print('  corr(成交量, 次日收益) = %.3f'%np.corrcoef(vol[:-1], ret.values[1:])[0,1])
lg = np.log(vol[1:]); lgv = np.log(vol.rolling(20).mean()[1:])
print('  corr(log量, 振幅%%) = %.3f'%np.corrcoef(lg, rng[1:])[0,1])
b=np.polyfit(lg, rng[1:],1); print('  回归: 振幅%% = %.3f × log(量) + %.3f'%(b[0],b[1]))
# 振幅分布
print('  振幅%%: p10 %.2f p25 %.2f 中位 %.2f p75 %.2f p90 %.2f 均值 %.2f'%(
 rng.quantile(.1),rng.quantile(.25),rng.median(),rng.quantile(.75),rng.quantile(.90),rng.mean()))
print('  10-02 振幅 7.50%% 分位 %.1f%% ; 10-06 振幅 5.72%% 分位 %.1f%%'%(100*(rng<7.50).mean(),100*(rng<5.72).mean()))
# 周内分布
print('\n===== 周内量能分布（252 窗口）=====')
wd = w.groupby(w.index.dayofweek)['Volume'].agg(['mean','median','count'])
names=['周一','周二','周三','周四','周五']
for i,nm in enumerate(names):
    if i in wd.index: print('  %s 均量 %10.0f 中位 %10.0f n=%d'%(nm,wd.loc[i,'mean'],wd.loc[i,'median'],wd.loc[i,'count']))

# ===== 6. 周线 =====
print('\n===== 周线结构 =====')
wk = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
wk = wk.dropna()
print('  周线根数 %d ; 最近 12 周:'%len(wk))
print(wk.tail(12).to_string(float_format=lambda x:'%.2f'%x))
wkc=wk['Close']
for n in [5,10,20,30]:
    print('  周线 SMA%d = %.2f'%(n, wkc.rolling(n).mean().iloc[-1]))
print('  最近 3 周涨跌: ' + ' '.join('%+.2f%%'%(wkc.pct_change().iloc[-i]*100) for i in [3,2,1]))
print('  周线 RSI(14) = %.2f'%(100-100/(1+rma(wkc.diff().clip(lower=0),14).iloc[-1]/rma((-wkc.diff()).clip(lower=0),14).iloc[-1])))
wke12=wkc.ewm(span=12,adjust=False).mean(); wke26=wkc.ewm(span=26,adjust=False).mean()
wm=wke12-wke26; ws=wm.ewm(span=9,adjust=False).mean()
print('  周线 MACD %.3f / Signal %.3f / Hist %.3f'%(wm.iloc[-1],ws.iloc[-1],(wm-ws).iloc[-1]))
print('  周线 ATR14 = %.2f = 现价 %.2f%%'%(atr_w(wk['High'],wk['Low'],wk['Close'],14).iloc[-1], 100*atr_w(wk['High'],wk['Low'],wk['Close'],14).iloc[-1]/411.04))

# ===== 7. 枢轴点 =====
print('\n===== 枢轴点（用 2026-10-06 这根 bar）=====')
H,L,C = 430.33,406.81,411.04
P=(H+L+C)/3
print('  P = (430.33+406.81+411.04)/3 = %.2f'%P)
print('  R1 = 2P - L = %.2f ; S1 = 2P - H = %.2f'%(2*P-L, 2*P-H))
print('  R2 = P + (H-L) = %.2f ; S2 = P - (H-L) = %.2f'%(P+(H-L), P-(H-L)))
print('  R3 = H + 2(P-L) = %.2f ; S3 = L - 2(H-P) = %.2f'%(H+2*(P-L), L-2*(H-P)))
print('  Fibonacci 枢轴: R1 = P+0.382(H-L) = %.2f ; R2 = P+0.618(H-L)=%.2f ; S1 = P-0.382(H-L)=%.2f ; S2 = P-0.618(H-L)=%.2f'%(
 P+0.382*(H-L), P+0.618*(H-L), P-0.382*(H-L), P-0.618*(H-L)))
print('  用前一日 ATR 推导的次日预期区间: 411.04 ± 29.62 = %.2f ~ %.2f'%(411.04-29.62, 411.04+29.62))
print('  用 0.5×ATR: %.2f ~ %.2f'%(411.04-14.81, 411.04+14.81))

# ===== 8. 缺口幅度历史 =====
print('\n===== 跳空幅度分布（252 窗口，开盘跳空 vs 前收）=====')
gap = (w['Open']/wc.shift(1)-1)*100
print('  跳空%%: p5 %.2f p25 %.2f 中位 %.2f p75 %.2f p95 %.2f ; |gap|>2%% 天数 %d (%.1f%%)'%(
 gap.quantile(.05),gap.quantile(.25),gap.median(),gap.quantile(.75),gap.quantile(.95),
 (gap.abs()>2).sum(), 100*(gap.abs()>2).mean()))
print('  10-02 跳空 %.2f%% 分位 %.1f%% ; 10-05 跳空 %+.2f%% ; 10-06 跳空 %.2f%%'%(
 (423.20/462.56-1)*100, 100*(gap<(423.20/462.56-1)*100).mean(),
 (430.50/415.29-1)*100, (426.60/441.64-1)*100))

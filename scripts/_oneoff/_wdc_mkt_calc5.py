# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）
# -*- coding: utf-8 -*-
"""WDC 口径 A 第五轮：RSI 历史分布与条件收益、300~380 薄区、上方阻力密集区。"""
import numpy as np, pandas as pd, yfinance as yf
END = pd.Timestamp('2026-10-06')
df = yf.download('WDC', start='2023-06-01', end='2026-10-08', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
df = df[['Open','High','Low','Close','Volume']].dropna()
df = df[df.index <= END].copy()
c,h,l,v = df['Close'],df['High'],df['Low'],df['Volume']
def wilder_rma(s,n): return s.ewm(alpha=1.0/n, adjust=False).mean()
d=c.diff(); rsi = 100-100/(1+wilder_rma(d.clip(lower=0),14)/wilder_rma((-d).clip(lower=0),14))

print('===== RSI(14) 全样本 n=%d =====' % rsi.dropna().shape[0])
print('  min %.2f @ %s ; max %.2f' % (rsi.min(), rsi.idxmin().date(), rsi.max()))
for q in [1,5,10,25,50]: print('  p%-2d %.2f'%(q, rsi.quantile(q/100)))
for t in [20,25,30,35,40,45]:
    print('  RSI<%d 天数 %d (%.1f%%)'%(t,(rsi<t).sum(),100*(rsi<t).mean()))
print('  当前 RSI %.2f → 全样本分位 %.1f%%，距 30 还差 %.2f 点，距历史最低 %.2f 点，距 40 阈值 %.2f 点'%(
    rsi.iloc[-1], 100*(rsi.dropna()<rsi.iloc[-1]).mean(), rsi.iloc[-1]-30, rsi.iloc[-1]-rsi.min(), rsi.iloc[-1]-40))

print('\n===== RSI<40 之后的前向收益（全样本）=====')
cond = rsi < 40
cnt=0; rows=[]
for i in np.where(cond.values)[0]:
    if i+10 >= len(c): continue
    cnt+=1
    rows.append((c.index[i].date(), rsi.values[i],
        (c.values[i+1]/c.values[i]-1)*100,(c.values[i+5]/c.values[i]-1)*100,(c.values[i+10]/c.values[i]-1)*100,
        (c.values[i+20]/c.values[i]-1)*100 if i+20<len(c) else np.nan))
for r in rows[-20:]:
    print('  %s RSI %.2f | 1d %+.2f%% 5d %+.2f%% 10d %+.2f%% 20d %s'%(r[0],r[1],r[2],r[3],r[4],'%+.2f%%'%r[5] if pd.notna(r[5]) else 'NA'))
f5=[r[3] for r in rows]; f10=[r[4] for r in rows]
print('  n=%d 5 日中位 %+.2f%% 胜率 %.1f%% ; 10 日中位 %+.2f%% 胜率 %.1f%%'%(
    len(f5),np.median(f5),100*np.mean(np.array(f5)>0),np.median(f10),100*np.mean(np.array(f10)>0)))

print('\n===== RSI 处于 [37,43] 区间之后的前向收益 =====')
cond2 = (rsi>=37)&(rsi<=43)
rows2=[]
for i in np.where(cond2.values)[0]:
    if i+10 >= len(c): continue
    rows2.append((c.index[i].date(), rsi.values[i],(c.values[i+5]/c.values[i]-1)*100,(c.values[i+10]/c.values[i]-1)*100))
for r in rows2[-15:]:
    print('  %s RSI %.2f | 5d %+.2f%% 10d %+.2f%%'%(r[0],r[1],r[2],r[3]))
f5b=[r[2] for r in rows2]
print('  n=%d 5 日中位 %+.2f%% 胜率 %.1f%%'%(len(f5b),np.median(f5b),100*np.mean(np.array(f5b)>0)))

# 300~380 薄区
w = df.tail(252); tp=(w['High']+w['Low']+w['Close'])/3
print('\n===== 252 根 300~380 成交分布（10 美元一档）=====')
for a in range(300,380,10):
    sel=(tp>=a)&(tp<a+10)
    print('  [%3d,%3d) %2d 根 量 %10.0f (%.2f%%)'%(a,a+10,sel.sum(),w['Volume'][sel].sum(),100*w['Volume'][sel].sum()/w['Volume'].sum()))

print('\n===== 252 根 500~800 成交分布（上方阻力，20 美元一档）=====')
for a in range(500,800,20):
    sel=(tp>=a)&(tp<a+20)
    print('  [%3d,%3d) %2d 根 量 %10.0f (%.2f%%)'%(a,a+20,sel.sum(),w['Volume'][sel].sum(),100*w['Volume'][sel].sum()/w['Volume'].sum()))

print('\n===== 2026-04-20 ~ 2026-04-30（下方薄架形成区）=====')
print(df.loc['2026-04-20':'2026-04-30'].to_string(float_format=lambda x:'%.2f'%x))

print('\n===== 2026-09-14 ~ 2026-09-18（9 月低点区）=====')
print(df.loc['2026-09-14':'2026-09-18'].to_string(float_format=lambda x:'%.2f'%x))

# 整数关口
print('\n===== 整数关口 =====')
for lv in [400,410,420,425,430,440,450,460,470,480,500,550,600,650,700,750,800]:
    print('  %4d : 距现价 %+.2f%%   = %.2f×ATR' % (lv, 100*(lv/411.04-1), abs(lv-411.04)/29.62))

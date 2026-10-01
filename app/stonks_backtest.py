from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import mean, pstdev, median
from typing import Any


def sma(values, period):
    out=[None]*len(values)
    if period<=0:
        return out
    total=0.0
    for i,v in enumerate(values):
        total += float(v)
        if i>=period:
            total -= float(values[i-period])
        if i>=period-1:
            out[i]=total/period
    return out


def atr(bars, period=14):
    trs=[]; prev=None
    for b in bars:
        h=float(b.get('h') or 0); l=float(b.get('l') or 0); c=float(b.get('c') or 0)
        tr=max(h-l, abs(h-prev) if prev is not None else 0, abs(l-prev) if prev is not None else 0)
        trs.append(tr); prev=c
    return sma(trs, period)


def rsi(closes, period=14):
    out=[None]*len(closes)
    if len(closes)<=period:
        return out
    gains=[0.0]*len(closes); losses=[0.0]*len(closes)
    for i in range(1,len(closes)):
        d=float(closes[i])-float(closes[i-1])
        gains[i]=max(d,0.0); losses[i]=max(-d,0.0)
    avg_gain=sum(gains[1:period+1])/period
    avg_loss=sum(losses[1:period+1])/period
    out[period]=100.0 if avg_loss==0 else 100-(100/(1+(avg_gain/avg_loss)))
    for i in range(period+1,len(closes)):
        avg_gain=((avg_gain*(period-1))+gains[i])/period
        avg_loss=((avg_loss*(period-1))+losses[i])/period
        out[i]=100.0 if avg_loss==0 else 100-(100/(1+(avg_gain/avg_loss)))
    return out


def max_drawdown(equity_curve):
    peak=None; max_dd=0.0
    for value in equity_curve:
        value=float(value)
        peak=value if peak is None else max(peak,value)
        if peak:
            max_dd=min(max_dd,(value-peak)/peak)
    return max_dd


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:
        return None


def _annualized_return(initial, final, bars):
    if initial<=0 or final<=0 or bars<=1:
        return 0.0
    years=max((bars-1)/252.0, 1/252.0)
    try:
        return ((final/initial)**(1/years)-1)*100.0
    except Exception:
        return 0.0


def _daily_returns(curve):
    out=[]
    for i in range(1,len(curve)):
        a=float(curve[i-1]); b=float(curve[i])
        if a>0:
            out.append((b/a)-1)
    return out


def _sharpe(curve):
    rs=_daily_returns(curve)
    if len(rs)<2:
        return None
    sd=pstdev(rs)
    if sd<=1e-12:
        return None
    return mean(rs)/sd*sqrt(252)


def _segments(curve):
    n=len(curve)
    if n<9:
        return []
    cuts=[0,n//3,(2*n)//3,n-1]
    out=[]
    for idx,(a,b) in enumerate(zip(cuts[:-1],cuts[1:]),1):
        start=float(curve[a]); end=float(curve[b])
        out.append({'segment':idx,'return_pct':round(((end/start)-1)*100,2) if start else 0})
    return out


def simulate(bars, strategy='trend', capital=10000.0, risk_pct=1.0, slippage_pct=0.05, start_index=0):
    """Pure deterministic long-only simulation.

    Signals use only closed bars and execute at the next bar open. Position size uses
    ATR from the prior closed bar, and the 2*ATR stop is actually enforced, so risk_pct
    represents a real stop-distance sizing rule rather than a cosmetic parameter.
    """
    strategy=str(strategy or 'trend').lower()
    if strategy not in ('trend','mean_reversion'):
        raise ValueError('Estrategia no válida')
    bars=[dict(b) for b in bars if all(k in b for k in ('o','h','l','c'))]
    if len(bars)<60:
        raise ValueError('Se necesitan al menos 60 barras')
    capital=float(capital); risk_pct=float(risk_pct); slippage_pct=float(slippage_pct)
    start_index=max(0,min(int(start_index or 0),len(bars)-1))
    closes=[float(b['c']) for b in bars]
    sma20=sma(closes,20); sma50=sma(closes,50); atr14=atr(bars,14); rsi14=rsi(closes,14)
    cash=capital; shares=0.0; entry_price=None; entry_index=None; stop_price=None
    trades=[]; equity_curve=[]; closed=[]; pending=None; slip=slippage_pct/100.0
    exposure_bars=0

    def exec_price(raw, side):
        raw=float(raw)
        return raw*(1+slip) if side=='buy' else raw*(1-slip)

    def close_position(raw_px, bar, reason, i):
        nonlocal cash, shares, entry_price, entry_index, stop_price
        px=exec_price(raw_px,'sell')
        qty=shares
        pnl=(px-(entry_price or px))*qty
        cash += qty*px
        held=max(0, i-(entry_index if entry_index is not None else i))
        row={'date':bar.get('t'),'side':'SELL','price':round(px,4),'qty':round(qty,6),'pnl':round(pnl,2),'exit_reason':reason,'bars_held':held}
        trades.append(row); closed.append(row)
        shares=0.0; entry_price=None; entry_index=None; stop_price=None

    def signal_at(i, has_position):
        if i < 0:
            return None
        if strategy=='trend' and sma20[i] is not None and sma50[i] is not None:
            if not has_position and sma20[i]>sma50[i]: return 'buy'
            if has_position and sma20[i]<sma50[i]: return 'sell'
        elif strategy=='mean_reversion' and rsi14[i] is not None:
            if not has_position and rsi14[i]<30: return 'buy'
            if has_position and rsi14[i]>70: return 'sell'
        return None

    # Walk-forward/out-of-sample mode: indicators may use warm-up history, but
    # portfolio activity starts exactly at start_index. The prior close may
    # legitimately produce an order for the evaluation window's first open.
    if start_index > 0:
        pending=signal_at(start_index-1, False)

    for i,b in enumerate(bars):
        if i < start_index:
            equity_curve.append(capital)
            continue
        o=float(b['o']); h=float(b['h']); l=float(b['l']); c=float(b['c'])
        # Signal decided on previous close; execution occurs now at today's open.
        if pending:
            side=pending; pending=None
            if side=='buy' and shares==0 and cash>0:
                prior_atr=atr14[i-1] if i>0 else None
                if prior_atr and prior_atr>0:
                    px=exec_price(o,'buy')
                    risk_cash=cash*(risk_pct/100.0)
                    stop_dist=2*float(prior_atr)
                    qty=min(cash/px, risk_cash/stop_dist if stop_dist else 0)
                    if qty>0:
                        cash-=qty*px; shares=qty; entry_price=px; entry_index=i
                        stop_price=max(0.01, px-stop_dist)
                        trades.append({'date':b.get('t'),'side':'BUY','price':round(px,4),'qty':round(qty,6),'pnl':None,'stop_price':round(stop_price,4)})
            elif side=='sell' and shares>0:
                close_position(o,b,'STRATEGY',i)

        # Intrabar protective stop. If market gaps through it, fill at the worse open.
        if shares>0 and stop_price is not None:
            exposure_bars += 1
            if o<=stop_price:
                close_position(o,b,'STOP_GAP',i)
            elif l<=stop_price:
                close_position(stop_price,b,'STOP_2ATR',i)
        elif shares>0:
            exposure_bars += 1

        equity=cash+shares*c
        equity_curve.append(equity)

        # Generate a signal from THIS CLOSED bar, for execution at NEXT open.
        if i+1<len(bars):
            sig=signal_at(i, shares>0)
            if sig: pending=sig

    if shares>0:
        close_position(closes[-1],bars[-1],'FINAL_CLOSE',len(bars)-1)
        equity_curve[-1]=cash

    final_equity=float(cash)
    sell_trades=[t for t in closed if t.get('pnl') is not None]
    pnls=[float(t['pnl']) for t in sell_trades]
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<0]
    gross_profit=sum(wins); gross_loss=abs(sum(losses))
    pf=(gross_profit/gross_loss) if gross_loss else (float('inf') if gross_profit>0 else None)
    eval_curve=equity_curve[start_index:] or [capital]
    eval_bars=max(1,len(bars)-start_index)
    ret=(final_equity/capital-1)*100
    dd=max_drawdown(eval_curve)*100
    cagr=_annualized_return(capital, final_equity, eval_bars)
    sharpe=_sharpe(eval_curve)
    calmar=(cagr/abs(dd)) if dd<0 else None
    avg_win=(sum(wins)/len(wins)) if wins else 0.0
    avg_loss=(sum(losses)/len(losses)) if losses else 0.0
    expectancy=(sum(pnls)/len(pnls)) if pnls else 0.0
    avg_held=(sum(t.get('bars_held',0) for t in sell_trades)/len(sell_trades)) if sell_trades else 0.0
    consec=0; max_consec=0
    for p in pnls:
        consec=consec+1 if p<0 else 0
        max_consec=max(max_consec,consec)
    benchmark_start=float(bars[start_index]['o']) if bars[start_index].get('o') else 0.0
    benchmark=((closes[-1]/benchmark_start)-1)*100 if benchmark_start else 0.0
    segment_returns=_segments(eval_curve)
    diagnostics=[]
    if eval_bars<252: diagnostics.append('Ventana evaluada inferior a ~1 año bursátil.')
    if len(sell_trades)<10: diagnostics.append('Muestra pequeña: menos de 10 operaciones cerradas.')
    if not losses and sell_trades: diagnostics.append('No hay operaciones perdedoras en la muestra; profit factor poco informativo.')
    if abs(dd)<1e-9 and sell_trades: diagnostics.append('Drawdown prácticamente nulo: revisar tamaño de muestra y frecuencia de operaciones.')

    return {
        'metrics':{
            'initial_equity':round(capital,2),'final_equity':round(final_equity,2),
            'return_pct':round(ret,2),'cagr_pct':round(cagr,2),'max_drawdown_pct':round(dd,2),
            'trades':len(sell_trades),'win_rate_pct':round((len(wins)/len(sell_trades)*100),2) if sell_trades else 0,
            'profit_factor':round(pf,3) if isinstance(pf,float) and pf!=float('inf') else ('∞' if pf==float('inf') else None),
            'expectancy_usd':round(expectancy,2),'avg_win_usd':round(avg_win,2),'avg_loss_usd':round(avg_loss,2),
            'sharpe':round(sharpe,3) if sharpe is not None else None,
            'calmar':round(calmar,3) if calmar is not None else None,
            'exposure_pct':round((exposure_bars/eval_bars*100),2),
            'avg_bars_held':round(avg_held,2),'max_consecutive_losses':max_consec,
            'benchmark_return_pct':round(benchmark,2),'vs_benchmark_pct':round(ret-benchmark,2),
        },
        'trades':trades,
        'equity_curve':equity_curve,
        'segments':segment_returns,
        'diagnostics':diagnostics,
        'model':{
            'lookahead_safe':True,'signal_timing':'closed_bar','execution_timing':'next_open',
            'position_sizing':'risk_pct / 2ATR','atr_source':'prior_closed_bar','protective_stop':'2ATR',
            'slippage_applied':True,'live_orders':False,'evaluation_start_index':start_index,'evaluation_bars':eval_bars,
        }
    }


def run_backtest(bars, strategy='trend', capital=10000.0, risk_pct=1.0, slippage_pct=0.05):
    base=simulate(bars,strategy,capital,risk_pct,slippage_pct)
    # Slippage sensitivity gives a deterministic robustness view without any LLM use.
    stress_levels=[]
    for mult in (1,2,3):
        slip=min(2.0,max(0.0,float(slippage_pct)*mult))
        sim=base if mult==1 else simulate(bars,strategy,capital,risk_pct,slip)
        m=sim['metrics']
        stress_levels.append({'label':f'{mult}x slippage','slippage_pct':round(slip,3),'return_pct':m['return_pct'],'max_drawdown_pct':m['max_drawdown_pct'],'trades':m['trades'],'profit_factor':m['profit_factor']})
    base['stress_tests']=stress_levels
    return base



def walk_forward(bars, strategy='trend', capital=10000.0, risk_pct=1.0, slippage_pct=0.05,
                 folds=4, train_bars=126, test_bars=63):
    """Rolling out-of-sample validation for a fixed deterministic strategy.

    There is no parameter fitting here: each fold uses prior bars strictly as
    indicator warm-up/context, resets capital at the first out-of-sample bar,
    and scores only the subsequent test window. This makes the result useful
    as a stability check without introducing LLMs or optimization leakage.
    """
    bars=[dict(b) for b in bars if all(k in b for k in ('o','h','l','c'))]
    folds=max(2,min(int(folds or 4),8))
    train_bars=max(60,min(int(train_bars or 126),504))
    test_bars=max(21,min(int(test_bars or 63),252))
    n=len(bars)
    possible=max(0,(n-train_bars)//test_bars)
    fold_count=min(folds,possible)
    if fold_count < 2:
        return {
            'ok':False,'folds':[],
            'summary':{'folds':0,'positive_folds':0,'positive_fold_pct':0.0,'trades':0},
            'diagnostics':['No hay histórico suficiente para al menos 2 ventanas walk-forward.']
        }

    first_test_start=n-(fold_count*test_bars)
    rows=[]
    for k in range(fold_count):
        test_start=first_test_start+k*test_bars
        test_end=min(n,test_start+test_bars)
        context_start=max(0,test_start-train_bars)
        subset=bars[context_start:test_end]
        eval_start=test_start-context_start
        sim=simulate(subset,strategy,capital,risk_pct,slippage_pct,start_index=eval_start)
        m=sim['metrics']
        rows.append({
            'fold':k+1,
            'train_start':bars[context_start].get('t'),'train_end':bars[test_start-1].get('t') if test_start>0 else None,
            'test_start':bars[test_start].get('t'),'test_end':bars[test_end-1].get('t'),
            'test_bars':test_end-test_start,
            'return_pct':m['return_pct'],'max_drawdown_pct':m['max_drawdown_pct'],
            'sharpe':m['sharpe'],'profit_factor':m['profit_factor'],'trades':m['trades'],
            'win_rate_pct':m['win_rate_pct'],'vs_benchmark_pct':m['vs_benchmark_pct'],
        })

    returns=[float(r['return_pct']) for r in rows]
    dds=[float(r['max_drawdown_pct']) for r in rows]
    sharpes=[float(r['sharpe']) for r in rows if r.get('sharpe') is not None]
    positive=sum(1 for x in returns if x>0)
    diagnostics=[]
    if sum(int(r.get('trades') or 0) for r in rows)<10:
        diagnostics.append('Walk-forward con pocas operaciones totales; interpretar con cautela.')
    if positive < len(rows):
        diagnostics.append('No todas las ventanas fuera de muestra fueron positivas.')
    return {
        'ok':True,
        'folds':rows,
        'summary':{
            'folds':len(rows),'positive_folds':positive,'positive_fold_pct':round(positive/len(rows)*100,1),
            'median_return_pct':round(median(returns),2),'worst_return_pct':round(min(returns),2),'best_return_pct':round(max(returns),2),
            'median_drawdown_pct':round(median(dds),2),'median_sharpe':round(median(sharpes),3) if sharpes else None,
            'trades':sum(int(r.get('trades') or 0) for r in rows),
            'avg_vs_benchmark_pct':round(mean(float(r.get('vs_benchmark_pct') or 0) for r in rows),2),
        },
        'diagnostics':diagnostics,
        'model':{'fixed_strategy':True,'parameter_optimization':False,'out_of_sample':True,'live_orders':False}
    }

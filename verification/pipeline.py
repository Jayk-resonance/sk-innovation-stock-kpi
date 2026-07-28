exec(open('vwap_method.py').read().split('def A(')[0])   # -> S (2025 baseline)
exec(open('eval2026.py').read())                          # -> E (2026 eval)
Ev={k:parse(v) for k,v in E.items()}

EH=["LG화학","S-Oil","롯데케미칼","포스코인터내셔널"]      # 에/화 60%
BS=["LG에너지솔루션","삼성SDI","에코프로비엠","포스코퓨처엠"]  # 배/소 40%
BASE=113109; P0=BASE*0.85; P100=BASE*1.15
def score(p): return 40*(p-P0)/(BASE-P0) if p<=BASE else 40+60*(p-BASE)/(P100-BASE)

def vwap(rows, method):
    if method=="A": return sum(r[3] for r in rows)/sum(r[2] for r in rows)
    else:           return sum(r[1]*r[2] for r in rows)/sum(r[2] for r in rows)

def tail(rows,n): return rows[-n:]
def rng(rows,s,e): return [r for r in rows if s<=r[0]<=e]

# 윈도우 정의: 2M=달력 2개월, 1M=달력 1개월, 1W=직전 5거래일
BW={"2M":lambda r: rng(r,"20251101","20251230"),
    "1M":lambda r: rng(r,"20251201","20251230"),
    "1W":lambda r: tail(r,5)}
EW={"2M":lambda r: rng(r,"20260528","20260727"),
    "1M":lambda r: rng(r,"20260628","20260727"),
    "1W":lambda r: tail(r,5)}

def adj(name, method, mode, base):
    src = S[name] if base else Ev[name]
    W   = BW if base else EW
    if mode=="잠정": return vwap(W["2M"](src),method)
    return sum(vwap(W[w](src),method) for w in ("2M","1M","1W"))/3

def run(method, mode):
    sk_r = adj("SK이노베이션",method,mode,False)/adj("SK이노베이션",method,mode,True)-1
    ch = [adj(n,method,mode,False)/adj(n,method,mode,True)-1 for n in EH]
    bs = [adj(n,method,mode,False)/adj(n,method,mode,True)-1 for n in BS]
    peer = 0.6*(sum(ch)/4)+0.4*(sum(bs)/4)
    x = sk_r-peer
    ev = adj("SK이노베이션",method,mode,False)*(1/(1-x))
    return dict(sk=sk_r,ch=sum(ch)/4,bs=sum(bs)/4,peer=peer,x=x,ev=ev,sc=score(ev))

print("="*76)
print("전체 파이프라인 — 방식 A(Σ대금/Σ량) vs 방식 B(Σ(종가×량)/Σ량)")
print("기준일 2025-12-30 / 평가일 2026-07-27 / 기준선 113,109원 고정")
print("="*76)
for mode in ("잠정","최종"):
    a,b=run("A",mode),run("B",mode)
    print(f"\n■ {mode}평가 방식 ({'2개월 VWAP' if mode=='잠정' else '2M·1M·1W 산술평균'})")
    print(f"  {'항목':<22}{'방식 A':>14}{'방식 B':>14}{'차이':>12}")
    print("  "+"-"*62)
    rows=[("SK 증감율",'sk','%'),("에/화 평균 증감율",'ch','%'),("배/소 평균 증감율",'bs','%'),
          ("Peer 증감율 (60:40)",'peer','%'),("상대 증감율 x",'x','%'),
          ("평가주가",'ev','원'),("점수",'sc','점')]
    for lab,k,u in rows:
        if u=='%':
            print(f"  {lab:<22}{a[k]*100:>13.2f}%{b[k]*100:>13.2f}%{(b[k]-a[k])*100:>11.3f}%p")
        elif u=='원':
            print(f"  {lab:<22}{a[k]:>13,.0f}원{b[k]:>13,.0f}원{b[k]-a[k]:>11,.0f}원")
        else:
            print(f"  {lab:<22}{a[k]:>13.2f}점{b[k]:>13.2f}점{b[k]-a[k]:>11.2f}점")

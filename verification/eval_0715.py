"""실제 평가일 2026-07-15 (상반기 잠정평가) 기준 산출."""
exec(open('vwap_method.py').read().split('def A(')[0])   # S = 2025 baseline
exec(open('eval2026.py').read()); exec(open('supp.py').read())
Ev={k:sorted(parse(E[k])+parse(SUP[k])) for k in E}

EH=["LG화학","S-Oil","롯데케미칼","포스코인터내셔널"]
BS=["LG에너지솔루션","삼성SDI","에코프로비엠","포스코퓨처엠"]
BASE=113109; P0=BASE*.85; P100=BASE*1.15
def score(p):
    s = 40*(p-P0)/(BASE-P0) if p<=BASE else 40+60*(p-BASE)/(P100-BASE)
    return max(0.0,min(100.0,s))                      # 미결4: 클리핑 확정
def vwap(r,m): return (sum(x[3] for x in r)/sum(x[2] for x in r) if m=="A"
                       else sum(x[1]*x[2] for x in r)/sum(x[2] for x in r))
def rng(r,s,e): return [x for x in r if s<=x[0]<=e]

# 윈도우: 평가일 역산 달력 기준 (미결3 기본가정), 1주=달력 7일 (미결6 확정)
BW={"2M":("20251101","20251230"),"1M":("20251201","20251230"),"1W":("20251224","20251230")}
EW={"2M":("20260516","20260715"),"1M":("20260616","20260715"),"1W":("20260709","20260715")}
def adj(n,m,mode,base):
    src,W=(S[n],BW) if base else (Ev[n],EW)
    if mode=="잠정": return vwap(rng(src,*W["2M"]),m)
    return sum(vwap(rng(src,*W[w]),m) for w in("2M","1M","1W"))/3
def run(m,mode):
    g=lambda n: adj(n,m,mode,False)/adj(n,m,mode,True)-1
    sk=g("SK이노베이션"); ch=sum(map(g,EH))/4; bs=sum(map(g,BS))/4
    peer=.6*ch+.4*bs; x=sk-peer; ev=adj("SK이노베이션",m,mode,False)/(1-x)
    return dict(sk=sk,ch=ch,bs=bs,peer=peer,x=x,ev=ev,sc=score(ev))

print("="*72)
print("실제 평가일 2026-07-15 (상반기 잠정평가) — 기준일 2025-12-30")
print("기준선 113,109원 고정 / 점수 0~100 클리핑 적용")
print("="*72)
for mode in ("잠정","최종"):
    a,b=run("A",mode),run("B",mode)
    print(f"\n■ {mode} 방식 ({'2개월 VWAP' if mode=='잠정' else '2M·1M·1W 산술평균'})")
    for lab,k in [("SK 증감율",'sk'),("에/화 평균",'ch'),("배/소 평균",'bs'),
                  ("Peer 증감율",'peer'),("상대 증감율 x",'x')]:
        print(f"  {lab:<16}A {a[k]*100:>8.2f}%   B {b[k]*100:>8.2f}%")
    print(f"  {'평가주가':<16}A {a['ev']:>8,.0f}원  B {b['ev']:>8,.0f}원")
    print(f"  {'점수':<16}A {a['sc']:>8.2f}점  B {b['sc']:>8.2f}점   (차이 {b['sc']-a['sc']:+.2f}점)")
print(f"\n※ 잠정 vs 최종 방식 격차: {run('B','최종')['sc']-run('B','잠정')['sc']:+.1f}점")

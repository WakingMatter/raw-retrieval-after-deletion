import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.family":"serif","font.size":9,"axes.spines.top":False,"axes.spines.right":False,
  "axes.edgecolor":"#52514e","axes.labelcolor":"#0b0b0b","xtick.color":"#52514e","ytick.color":"#52514e","pdf.fonttype":42})
C={"RR":"#2a78d6","CM":"#eb6834","Route":"#1baf7a","RR2":"#eda100"}
# --- Figure 1: E4 budget sweep (values from DRAFT-v7 Tables 9-10) ---
B=[125,500,1000,2000,4000,8000]
rr=[.4312,.5766,.6109,.6141,.6188,.6219]
rr2=[.4359,.6047,.6922,.7016,.7250,.7312]
route=[.2469,.3984,.4891,.5250,.5422,.5828]
cm=[.2281,.4297,.4969,.5625,.5719,.5797]  # B125: share 1/5, cap 25; others F1 share 1/5
fig,(ax,bx)=plt.subplots(2,1,figsize=(5.2,4.6),sharex=True,gridspec_kw={"height_ratios":[2.9,1.6],"hspace":0.12})
for y,k,lab,m,ls in [(rr2,"RR2","Two-step raw retrieval (RR-2hop)","D","--"),(rr,"RR","Reranked raw retrieval (RR)","o","-"),
                     (cm,"CM","Computed memory, summaries served (CM)","s","-"),(route,"Route","Computed memory, no summaries (Route-only)","^",":")]:
    ax.plot(B,y,color=C[k],lw=2,ls=ls,marker=m,ms=5,label=lab,markeredgecolor="#fcfcfb",markeredgewidth=0.8)
ax.plot([2000],[.550],marker="s",ms=7,mfc="none",mec=C["CM"],mew=1.5,ls="none")
ax.plot([2000],[.607],marker="o",ms=7,mfc="none",mec=C["RR"],mew=1.5,ls="none")
ax.annotate("primary study (E2):\nRR .607, CM .550",xy=(2000,.55),xytext=(2900,.40),fontsize=7.5,color="#52514e",
            arrowprops=dict(arrowstyle="-",color="#9a9893",lw=0.8))
ax.set_xscale("log"); ax.minorticks_off(); ax.set_ylabel("Accuracy (strict)")
ax.set_ylim(.15,.78); ax.grid(axis="y",color="#e4e3df",lw=0.6); ax.set_axisbelow(True)
ax.legend(frameon=False,fontsize=7.5,loc="lower right")
ax.text(-0.13,1.0,"a",transform=ax.transAxes,fontweight="bold",va="top")
# panel b: CM - RR, paired 95% CI (Table G1; B125 = share 1/5, cap 25)
d=[-.2031,-.1469,-.1141,-.0516,-.0469,-.0422]
lo=[-.2525,-.1884,-.1424,-.0858,-.0848,-.0864]; hi=[-.1538,-.1053,-.0857,-.0173,-.0089,.0021]
d100=[v*100 for v in d]; err=[[ (v-l)*100 for v,l in zip(d,lo)],[(h-v)*100 for v,h in zip(d,hi)]]
bx.axhline(0,color="#52514e",lw=0.8)
bx.axhline(5,color="#9a9893",lw=0.8,ls="--")
bx.text(160,5.6,"+5-point bar for a meaningful advantage",fontsize=7,color="#52514e",va="bottom",ha="left")
bx.errorbar(B,d100,yerr=err,fmt="s",color=C["CM"],ms=4.5,capsize=2.5,lw=1.2,mec="#fcfcfb",mew=0.8)
bx.set_ylabel("CM − RR\n(points, 95% CI)"); bx.set_ylim(-27,10)
bx.set_xscale("log"); bx.set_xticks(B); bx.set_xticklabels([str(b) for b in B]); bx.minorticks_off()
bx.set_xlabel("Evidence budget B (estimated tokens, log scale)")
bx.grid(axis="y",color="#e4e3df",lw=0.6); bx.set_axisbelow(True)
bx.text(-0.13,1.0,"b",transform=bx.transAxes,fontweight="bold",va="top")
bx.set_xlim(100,10500)
fig.subplots_adjust(left=0.15,right=0.98,top=0.98,bottom=0.1); fig.savefig("fig1-budget-sweep.pdf"); fig.savefig("fig1-budget-sweep.png",dpi=160)
# --- Figure 3: accuracy by class (DRAFT-v7 Table 6) ---
import numpy as np
cls=["Aggregation","Derived\nattribute","Two-hop\n(bridge-linked)","Current\nvalue"]
cmv=[.472,.472,.506,.750]; rov=[.413,.356,.534,.763]; rrv=[.544,.363,.750,.772]
x=np.arange(4); w=.26
fig,ax=plt.subplots(figsize=(5.2,2.6))
for i,(v,k,lab) in enumerate([(rrv,"RR","RR"),(cmv,"CM","CM"),(rov,"Route","Route-only")]):
    ax.bar(x+(i-1)*w,v,w-0.02,color=C[k],label=lab,edgecolor="#fcfcfb",linewidth=1)
diffs=["−7.2","+10.9","−24.4","−2.2"]
for xi,d,top in zip(x,diffs,[max(a,b,c) for a,b,c in zip(cmv,rov,rrv)]):
    ax.text(xi,top+.03,f"CM − RR {d}",ha="center",fontsize=7.5,color="#0b0b0b")
ax.set_xticks(x); ax.set_xticklabels(cls); ax.set_ylabel("Accuracy (strict)"); ax.set_ylim(0,.9)
ax.grid(axis="y",color="#e4e3df",lw=0.6); ax.set_axisbelow(True); ax.legend(frameon=False,fontsize=7.5,ncol=3,loc="upper left")
fig.tight_layout(); fig.savefig("fig3-by-class.pdf"); fig.savefig("fig3-by-class.png",dpi=160)
print("ok")

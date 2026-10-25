# Erdős 最小重叠问题：从定义到搜索、到上界有效性的完整逻辑链

> 本文档为 version 4 的理论基础。每一步给出严格陈述与证明；引用文献的结论均另附自洽证明，不依赖引用正确性。
> 记号：$\lambda$ 为 Lebesgue 测度，$\|\cdot\|_1$ 为 $L^1([0,2])$ 范数，$[m]=\{1,\dots,m\}$。

## 0. 结论摘要

1. 原始问题的常数 $\mu=\lim_{n\to\infty}M(n)/n$ 存在，且
   $$\mu=\inf_{f\in\mathcal F}C(f)=\inf_{f\in\mathcal F_{\{0,1\}}}C(f)=\lim_{N\to\infty}\mu_N ,$$
   其中 $\mathcal F$ 是 $[0,2]$ 上取值于 $[0,1]$、积分为 1 的可测函数，$\mathcal F_{\{0,1\}}$ 是其中的指示函数，$\mu_N$ 是 $N$ 格等宽阶梯函数上的最小值（定理 5.1，文献中归于 Swinnerton-Dyer，见 Haugland 2016 §1）。
2. 因此 evaluator 接受的**任何**合法网格数组 $v$（$0\le v_i\le1$、$\sum v_i=N/2$）都满足 $\mu\le C(v)$，并且 $M(n)/n\ge\mu$ 对每个 $n$ 成立。分数值不是"松弛作弊"：分数值与二值的最优值相同（推论 5.2）。
3. 搜索只剩三类 gap：浮点误差（精确有理复核后为 0）、网格 gap $\mu_N-\mu\ge0$（只影响可达值，不影响上界有效性）、最优性 gap（未知）。没有松弛 gap。
4. 同一网格上"分数值 → 0/1"的差距（round 3 实测 +4.6%）是固定分辨率现象，随分辨率 $n\to\infty$ 以 $O(\sqrt{\log n/n})$ 消失（定理 4.3）；换 $N$ 重采样改变的是函数本身，`np.repeat` 上采样严格保持分数（命题 6.2）。

## 1. 原始问题

**定义 1.1.** 对正整数 $n$，把 $[2n]$ 划分为 $A\sqcup B$，$|A|=|B|=n$。对整数 $k$ 定义
$$M_k(A)=\#\{(a,b)\in A\times B:\ a-b=k\}=\sum_{x\in\mathbb Z}\mathbf 1_A(x+k)\,\mathbf 1_B(x),$$
$$M(n)=\min_{A}\ \max_{k\in\mathbb Z}M_k(A).$$
$M_k(A)=0$ 当 $|k|\ge 2n$，所以 max 只需取 $|k|\le 2n-1$。Erdős 问 $M(n)/n$ 的渐近行为。

**文献界**（截至 2026-10，来源：teorth/optimizationproblems 常数 1b、arXiv:1609.08000、arXiv:2201.05704）：

| 类型 | 值 | 来源 |
|---|---|---|
| 下界 | 0.379005 | White 2022, arXiv:2201.05704 |
| 上界 | 0.3809268534 | Haugland 2016, arXiv:1609.08000（阶梯函数） |
| 上界 | 0.380924 | AlphaEvolve (Georgiev–Gómez-Serrano–Tao–Wagner 2025) |
| 上界 | 0.380876 | TTT-Discover (2026) |
| 本仓库热启动 | 0.38086768 | best_results/…/erdos_minimum_overlap_best_construction.json，$N=2400$（v4 用精确有理复核确认） |

2026 年另有声称更高下界的工作，本文档未核实，不使用。下面只需要平凡界：$1/4\le\mu\le1/2$（命题 2.2）。

## 2. 连续泛函

**定义 2.1.** $\mathcal F=\{f:[0,2]\to[0,1]\ \text{可测},\ \int_0^2f=1\}$。对 $s\in\mathbb R$ 令 $D_s=\{x\in[0,2]:x+s\in[0,2]\}$，
$$A_f(s)=\int_{D_s}f(x)\bigl(1-f(x+s)\bigr)\,dx,\qquad C(f)=\sup_{s\in\mathbb R}A_f(s).$$
$|s|\ge2$ 时 $D_s$ 为零测集，$A_f(s)=0$。

**命题 2.2（平凡界）.** 对任意 $f\in\mathcal F$，$C(f)\ge 1/4$；且 $C(1/2)=1/2$，故 $\inf_{\mathcal F}C\le 1/2$。

*证明.* 由 Fubini，作变量替换 $y=x+s$：
$$\int_{-2}^{2}A_f(s)\,ds=\int_0^2\!\!\int_0^2 f(x)(1-f(y))\,dy\,dx=\Bigl(\int f\Bigr)\Bigl(2-\int f\Bigr)=1 .$$
区间长度为 4，故 $\sup_sA_f(s)\ge 1/4$。对 $f\equiv1/2$，$A_f(s)=\lambda(D_s)/4=(2-|s|)/4$，最大值 $1/2$ 于 $s=0$。$\square$

**命题 2.3（对称性）.** 令 $Rf(x)=f(2-x)$，$Kf(x)=1-f(x)$。则 $R,K$ 把 $\mathcal F$ 映到 $\mathcal F$，且 $A_{Rf}(s)=A_{Kf}(s)=A_f(-s)$，故 $C(Rf)=C(Kf)=C(RKf)=C(f)$。$\{I,R,K,RK\}$ 构成 Klein 四元群。

*证明.* $\int Kf=2-1=1$，$\int Rf=1$，取值仍在 $[0,1]$。
$A_{Rf}(s)=\int f(2-x)(1-f(2-x-s))dx$；令 $z=2-x$：$=\int f(z)(1-f(z-s))dz=A_f(-s)$（积分域自动对应 $D_{-s}$）。
$A_{Kf}(s)=\int(1-f(x))f(x+s)dx$；令 $z=x+s$：$=\int f(z)(1-f(z-s))dz=A_f(-s)$。
sup 取遍 $s\in\mathbb R$，与 $s\mapsto-s$ 无关。$RK=KR$，$R^2=K^2=I$。$\square$

**命题 2.4（非凸性）.** 对固定 $s\ne0$，$f\mapsto A_f(s)$ 是不定二次泛函：存在方向 $\varphi,\psi$ 使其沿 $\varphi$ 严格凹、沿 $\psi$ 严格凸。因此搜索问题没有凸性保证，局部方法可能停在非全局的局部极小。

*证明.* $A_{f+t\varphi}(s)$ 中 $t^2$ 的系数为 $-Q_s(\varphi)$，$Q_s(\varphi)=\int_{D_s}\varphi(x)\varphi(x+s)dx$。取 $0<\delta<s/2$ 且 $2s+\delta<2$（$s>0$ 时；$s<0$ 由对称性），令 $\varphi=\mathbf 1_{[0,\delta]}+\mathbf 1_{[s,s+\delta]}$，$\psi=\mathbf 1_{[0,\delta]}-\mathbf 1_{[s,s+\delta]}$。$\varphi(x)\varphi(x+s)$ 只在 $x\in[0,\delta]$ 上非零（$x\in[s,s+\delta]$ 时 $x+s\in[2s,2s+\delta]$ 在支撑外），故 $Q_s(\varphi)=\delta>0$，$Q_s(\psi)=-\delta<0$。$\square$

（$s=0$ 时 $A_f(0)=\int f-\int f^2$ 是凹的；但 $C$ 是对所有 $s$ 取 sup，整体非凸。）

## 3. $L^1$ 稳定性

**命题 3.1.** 对可测 $f,g:[0,2]\to[0,1]$ 与任意 $s$，$|A_f(s)-A_g(s)|\le2\|f-g\|_1$，从而 $|C(f)-C(g)|\le2\|f-g\|_1$。

*证明.* 恒等式
$f(x)(1-f(x+s))-g(x)(1-g(x+s))=(f(x)-g(x))(1-f(x+s))+g(x)(g(x+s)-f(x+s))$。
由 $0\le 1-f,\,g\le1$，在 $D_s$ 上积分，第一项绝对值 $\le\|f-g\|_1$，第二项 $\le\int_{D_s}|g(x+s)-f(x+s)|dx\le\|f-g\|_1$。对 $s$ 取 sup，用 $|\sup a-\sup b|\le\sup|a-b|$。$\square$

（即 proof.md 的同名结论，此处不需要质量约束。）

## 4. 离散 ⇄ 连续

记 $N$ 格等宽网格 $\Delta=2/N$，$I_i=[i\Delta,(i+1)\Delta)$，$i=0,\dots,N-1$。对 $v\in[0,1]^N$ 令 $f_v=\sum_iv_i\mathbf 1_{I_i}$，并记
$$\mathcal F_N=\Bigl\{v\in[0,1]^N:\ \sum_iv_i=N/2\Bigr\}\quad(\Leftrightarrow f_v\in\mathcal F),\qquad
c_k(v)=\sum_{i:\,0\le i,\,i+k\le N-1}v_i(1-v_{i+k}).$$

**引理 4.1（网格平移取到 sup）.** 对 $v\in[0,1]^N$，
$$A_{f_v}(s)=\sum_{k=-(N-1)}^{N-1}c_k(v)\,\tau(s-k\Delta),\qquad \tau(u)=(\Delta-|u|)_+ .$$
因此 $A_{f_v}$ 是连续分段线性函数，在每个 $[k\Delta,(k+1)\Delta]$ 上线性，$A_{f_v}(k\Delta)=\Delta\,c_k(v)$，并且
$$C(f_v)=\Delta\max_{|k|\le N-1}c_k(v).$$

*证明.* $x\in D_s$ 当且仅当 $x+s\in[0,2)$（差一个零测集），而 $[0,2)=\bigsqcup_jI_j$。所以在 $D_s$ 上 $1-f_v(x+s)=\sum_j(1-v_j)\mathbf 1_{I_j-s}(x)$，
$$A_{f_v}(s)=\sum_{i,j}v_i(1-v_j)\,\lambda\bigl(I_i\cap(I_j-s)\bigr).$$
$I_i$ 与 $I_j-s$ 是左端点分别为 $i\Delta$、$j\Delta-s$ 的两个长 $\Delta$ 区间，交的长度为 $(\Delta-|(j-i)\Delta-s|)_+=\tau(s-(j-i)\Delta)$。按 $k=j-i$ 归并即得公式。$\{\tau(\cdot-k\Delta)\}_k$ 是节点 $k\Delta$ 上的帽函数基，故 $A_{f_v}$ 是以 $(k\Delta,\Delta c_k)$ 为节点的分段线性插值；$|s|\ge N\Delta=2$ 时为 0。连续分段线性函数在紧区间上的最大值在节点处取到，而 $c_k\ge0$。$\square$

**命题 4.2（嵌入）.** 对 $A\subset[2n]$，$|A|=n$，令 $N=2n$，$v_{x-1}=\mathbf 1_A(x)$，$f_A=f_v$（$\Delta=1/n$）。则 $f_A\in\mathcal F_{\{0,1\}}$ 且
$$C(f_A)=\frac1n\max_kM_k(A).$$
因此对每个 $n$：$\ M(n)/n=\min_{|A|=n}C(f_A)\ \ge\ \inf_{\mathcal F_{\{0,1\}}}C\ \ge\ \inf_{\mathcal F}C$。

*证明.* $\int f_A=n\cdot\frac1n=1$。由引理 4.1，$C(f_A)=\frac1n\max_kc_k$，而 $c_k=\#\{x\in A:\ x+k\in B\}=M_{-k}(A)$（$x+k\notin[2n]$ 的项不计入，与 $M$ 的定义一致）。$k$ 取遍对称区间，max 不变。$\square$

**定理 4.3（随机舍入）.** 设 $v\in\mathcal F_N$，$n\ge1$。则
$$M(n)\ \le\ n\,C(f_v)+2(N-1)+2\sqrt{n\log(8n)} .$$
若 $N\mid 2n$，可去掉 $2(N-1)$ 项。

*证明.* (i) *细网格平均.* 细格 $J_x=[(x-1)/n,x/n)$，$x\in[2n]$，令 $p_x=n\int_{J_x}f_v\in[0,1]$，$g=\sum_xp_x\mathbf 1_{J_x}$。则 $\int g=\int f_v=1$，即 $\sum_xp_x=n$。粗格边界 $i\Delta$（$1\le i\le N-1$）至多落在 $N-1$ 个细格的内部；其余细格上 $f_v$ 为常数 $=p_x$。在前者上 $|g-f_v|\le1$，故 $\|g-f_v\|_1\le(N-1)/n$，由命题 3.1，$C(g)\le C(f_v)+2(N-1)/n$。若 $N\mid2n$，每个粗格恰是若干细格之并，$g=f_v$。

(ii) *期望.* 记 $S_k(y)=\sum_{x:\,x,\,x+k\in[2n]}y_x(1-y_{x+k})$。由引理 4.1（网格 $2n$，$\Delta=1/n$），$C(g)=\frac1n\max_kS_k(p)$。取独立 $X_x\sim\mathrm{Bernoulli}(p_x)$。$k\ne0$ 时各项两个因子独立，$\mathbb ES_k(X)=S_k(p)$；$k=0$ 时 $X_x(1-X_x)\equiv0$，$S_0(X)=0$。另 $T=\sum_xX_x$，$\mathbb ET=n$。

(iii) *有界差分.* 固定 $k\ne0$。$X_x$ 只出现在两项 $X_x(1-X_{x+k})$ 与 $X_{x-k}(1-X_x)$（越界项视为 0）。$X_x$ 由 0 变 1 时 $S_k$ 变化 $(1-X_{x+k})-X_{x-k}\in\{-1,0,1\}$。故每个坐标的有界差分常数为 1；$T$ 同样为 1。McDiarmid 不等式给出
$$\mathbb P\bigl(S_k(X)-S_k(p)\ge t\bigr)\le e^{-2t^2/(2n)}=e^{-t^2/n},\qquad \mathbb P(|T-n|\ge t)\le2e^{-t^2/n}.$$

(iv) *Union bound.* $k\ne0$、$|k|\le2n-1$ 共 $4n-2$ 个，加上 $T$ 的两侧，失败概率 $\le4n\,e^{-t^2/n}$。取 $t=\sqrt{n\log(8n)}$，失败概率 $\le1/2<1$。故存在 $y\in\{0,1\}^{2n}$，对所有 $k\ne0$ 有 $S_k(y)\le S_k(p)+t$，且 $|\sum y-n|\le t$。

(v) *精确修正质量.* 若 $\sum y>n$，把 $\sum y-n$ 个 1 改为 0；若不足，把相应个数的 0 改为 1。由 (iii)，每次改动使每个 $S_k$（$k\ne0$）变化至多 1，$S_0$ 恒为 0。得到 $|A|=n$，且
$$\max_kM_k(A)=\max_kS_k(y')\le\max_kS_k(p)+2t=n\,C(g)+2t\le n\,C(f_v)+2(N-1)+2t.\ \square$$

## 5. 主定理：分数值、二值与原始问题的等价

**引理 5.0（格平均）.** $E_N f=\sum_i\bigl(\frac1\Delta\int_{I_i}f\bigr)\mathbf 1_{I_i}$。则 $E_N$ 把 $\mathcal F$ 映入 $\{f_v:v\in\mathcal F_N\}$，是 $L^1$ 压缩，且 $\|E_Nf-f\|_1\to0$（$N\to\infty$）。

*证明.* 平均值在 $[0,1]$ 中、质量不变；$\int_{I_i}|\text{avg}(h)|\le\int_{I_i}|h|$ 给出压缩性。对连续 $\varphi$，每格上 $|E_N\varphi-\varphi|\le\omega_\varphi(\Delta)$，故 $\|E_N\varphi-\varphi\|_1\le2\omega_\varphi(\Delta)$。连续函数在 $L^1$ 中稠密：$\|E_Nf-f\|_1\le\|E_N(f-\varphi)\|_1+\|E_N\varphi-\varphi\|_1+\|\varphi-f\|_1\le2\|f-\varphi\|_1+2\omega_\varphi(\Delta)$，先取 $\varphi$ 再令 $N\to\infty$。$\square$

定义 $\mu^*=\inf_{\mathcal F}C$，$\mu_N=\min_{v\in\mathcal F_N}C(f_v)$。$\mathcal F_N$ 非空紧集，$v\mapsto\Delta\max_kc_k(v)$ 连续，故 min 取到。

**定理 5.1（Swinnerton-Dyer；本文自证）.**
(a) 对每个 $n$，$M(n)/n\ge\mu^*$。
(b) $\mu_N\ge\mu^*$，且 $\mu_N\to\mu^*$。
(c) $\mu:=\lim_{n\to\infty}M(n)/n$ 存在且等于 $\mu^*$。
(d) $\mu^*=\inf_{[0,1]\text{ 值阶梯}}C=\inf_{0/1\text{ 阶梯}}C=\inf_{\mathcal F_{\{0,1\}}}C$。

*证明.* (a) 命题 4.2。
(b) $f_v\in\mathcal F$ 给出 $\mu_N\ge\mu^*$。对任意 $f\in\mathcal F$，$E_Nf=f_v$ 对某 $v\in\mathcal F_N$，由命题 3.1 与引理 5.0，$\mu_N\le C(E_Nf)\le C(f)+2\|E_Nf-f\|_1\to C(f)$。所以 $\limsup\mu_N\le C(f)$，对 $f$ 取 inf 得 $\limsup\mu_N\le\mu^*$。
(c) 对固定 $N$ 取 $v$ 达到 $\mu_N$。定理 4.3 除以 $n$ 后令 $n\to\infty$：$\limsup_nM(n)/n\le\mu_N$。再令 $N\to\infty$，由 (b) 得 $\limsup\le\mu^*$。结合 (a) 的 $\liminf\ge\mu^*$。
(d) 包含关系给出 $\mu^*\le\inf_{[0,1]\text{阶梯}}\le\inf_{0/1\text{阶梯}}$ 以及 $\mu^*\le\inf_{\mathcal F_{\{0,1\}}}\le\inf_{0/1\text{阶梯}}$。另一方面，命题 4.2 中最优的 $f_A$ 是 0/1 阶梯函数，$\inf_{0/1\text{阶梯}}C\le M(n)/n$ 对所有 $n$ 成立，令 $n\to\infty$ 由 (c) 得 $\le\mu^*$。$\square$

**推论 5.2（上界有效性，无松弛 gap）.** 对任意 $N$ 与任意 $v\in\mathcal F_N$：
$$\mu\ \le\ \mu_N\ \le\ C(f_v)=\Delta\max_kc_k(v).$$
特别地，proof.md 中"$C^*_{\rm rel}\le C^*_{\rm bin}$，反向需另证"一节的两个全局最优值相等：$C^*_{\rm rel}=C^*_{\rm bin}=\mu$。分数值数组给出的数值就是原问题常数 $\mu$ 的合法上界，不需要二值化。

**注.** 推论 5.2 是关于极限常数 $\mu$ 的上界，不是关于某个固定 $n$ 的 $M(n)/n$ 的上界。后者只能通过定理 4.3 得到，且带有 $O(\sqrt{\log n/n})$ 误差（第 8 节）。文献中的上界（Haugland、AlphaEvolve、TTT-Discover）都是这个意义上的上界。

## 6. 等价的搜索问题与搜索方式

**搜索问题.** 选定 $N$，求
$$\min_{v\in\mathcal F_N}\ \Phi(v),\qquad \Phi(v)=\Delta\max_{|k|\le N-1}c_k(v).$$
由推论 5.2，任何可行 $v$ 都给出 $\mu\le\Phi(v)$。最优值 $\mu_N\downarrow$（沿加细）并收敛到 $\mu$。

**命题 6.1（evaluator 精确性）.** legacy evaluator 计算 `max(np.correlate(h, 1-h, 'full')) * 2/N`。numpy 约定 `correlate(a, w, 'full')[k] = Σ_n a[n+k] w[n]`，$k=-(N-1),\dots,N-1$，即 $\sum_nh_{n+k}(1-h_n)=c_{-k}(h)$。$k$ 取遍对称区间，故在精确算术下该值等于 $\Phi(h)=C(f_h)$（引理 4.1）。浮点误差见第 9 节 (G1)。

**命题 6.2（repeat 不变性与单调加细）.** 对整数 $r\ge1$，令 $v^{(r)}=\texttt{np.repeat}(v,r)\in[0,1]^{rN}$。则 $f_{v^{(r)}}=f_v$ 作为 $[0,2]$ 上的函数恒等，$v^{(r)}\in\mathcal F_{rN}$，$\Phi(v^{(r)})=\Phi(v)$。因此 $\mu_{rN}\le\mu_N$。

*证明.* 第 $i$ 个粗格 $I_i$ 恰为细格 $ri,\dots,ri+r-1$ 之并，各细格取值 $v_i$；$\sum v^{(r)}=r\cdot N/2=rN/2$。$\Phi$ 只依赖函数 $f$（引理 4.1 的 $C(f_v)$），故相等。$\square$

**注 6.3（"换 N 分数剧变"的解释）.** 以下操作都产生**另一个函数**，分数变化没有理由小：
- 插值/抽样重采样到新的 $N'$（$N'\nmid$ 原网格结构时）；
- 让同一个程序在新的 $N'$ 上重新运行（程序输出的是另一个数组）；
- 固定网格上的二值化。

由命题 3.1，分数变化 $\le2\|f-g\|_1$，但这个 $L^1$ 距离本身可以很大。所以 round 3 观察到的剧变不说明上界失效：每个合法数组的分数对它自己的阶梯函数都精确有效。唯一保证不变的变换是命题 6.2 的 repeat 和命题 2.3 的对称变换（数组层面：`v[::-1]`、`1-v`、`(1-v)[::-1]`）。

**搜索含义（由上面的数学事实直接推出，不涉及解的形状猜测）.**
1. 分数精确，$10^{-7}$ 级的改进是真实的，不是噪声；比较时必须看足够多位小数。
2. 加细是单调安全的：在 $N$ 上的解 repeat 到 $rN$ 后分数不变，然后在 $rN$ 上继续优化只会更好。大 $N$ 的可达值 $\mu_{rN}\le\mu_N$。
3. 目标是有限个不定二次函数的最大值（命题 2.4）：非光滑、非凸。一阶条件见第 7 节；局部方法需要多起点或结构多样性。
4. 对称轨道上的解等价（命题 2.3），衡量"新结构"必须在轨道上取最小距离。

## 7. 解的必然结构（一阶必要条件）

对 $v\in\mathcal F_N$ 令 $K(v)=\{k:\ c_k(v)=\max_jc_j(v)\}$（active shifts），并记
$$\frac{\partial c_k}{\partial v_j}=\mathbf 1[\,0\le j+k\le N-1\,](1-v_{j+k})-\mathbf 1[\,0\le j-k\le N-1\,]\,v_{j-k}.$$

**定理 7.1（KKT 必要条件）.** 若 $v^*$ 是 $\Phi$ 在 $\mathcal F_N$ 上的局部极小，则存在 $\lambda\in\Delta^{K(v^*)}$（$\lambda_k\ge0$，$\sum\lambda_k=1$）与 $\tau\in\mathbb R$，使 $g=\sum_{k\in K(v^*)}\lambda_k\nabla c_k(v^*)$ 满足
$$g_i=\tau\ (0<v^*_i<1),\qquad g_i\ge\tau\ (v^*_i=0),\qquad g_i\le\tau\ (v^*_i=1).$$

*证明.* 令 $T=\{d:\sum d_i=0,\ d_i\ge0\text{ 若 }v^*_i=0,\ d_i\le0\text{ 若 }v^*_i=1\}$。$\mathcal F_N$ 是多面体，对 $d\in T$ 与充分小的 $t>0$ 有 $v^*+td\in\mathcal F_N$。有限个 $C^1$ 函数的最大值沿方向可微（Danskin）：$\Phi'(v^*;d)=\Delta\max_{k\in K}\nabla c_k\cdot d$。局部极小给出 $\max_{k\in K}\nabla c_k\cdot d\ge0$，$\forall d\in T$。
令 $D=T\cap[-1,1]^N$（紧凸），$L(\lambda,d)=\sum_k\lambda_k\nabla c_k\cdot d$ 双线性。由 von Neumann 极小极大定理，$\max_{\lambda}\min_{d\in D}L=\min_{d\in D}\max_\lambda L\ge0$。取达到者 $\lambda$，则 $g\cdot d\ge0$ 对 $D$ 成立，从而对锥 $T$ 成立。
对 $i\ne j$，只要 $e_i-e_j\in T$ 就有 $g_i\ge g_j$。$e_i-e_j\in T$ 当且仅当 $v^*_i<1$ 且 $v^*_j>0$。因此：两个自由坐标 $g$ 相等，记为 $\tau$；$v_i^*=0$、$j$ 自由时 $g_i\ge\tau$；$v_i^*=1$、$j$ 自由时 $g_i\le\tau$。若没有自由坐标，对 $v_i^*=0$、$v_j^*=1$ 有 $g_i\ge g_j$，取 $\tau\in[\max_{v_j^*=1}g_j,\ \min_{v_i^*=0}g_i]$（非空）。$\square$

**注 7.2.**
- 若 $|K(v^*)|=1$，定理要求单个 $\nabla c_k$ 在所有自由坐标上取同一值，这是很强的等式组。这里不把它写成定理，只作诊断：`n_active_shifts` 记录 active 集的大小，active 集很小且有许多自由坐标时，通常仍可下降。
- 定理 7.1 只是必要条件。非凸性（命题 2.4）下 KKT 点可能不是全局最优；本文不对最优解的形状作任何断言。
- 若 $v^*$ 最优，则 $v^*[::-1]$、$1-v^*$、$(1-v^*)[::-1]$ 也最优（命题 2.3）。

## 8. 从搜索解恢复原问题的解

**8.1 上界不需要恢复.** 由推论 5.2，$\mu\le\Phi(v)$ 直接成立。文献上界就是这样报告的（Haugland 2016："one way to estimate lim M(n)/n from above is to give step functions … rather than looking for explicit partitions"）。

**8.2 显式划分（若需要）.** 由定理 4.3，对 $n$ 满足 $N\mid2n$，存在划分使
$$\frac{M(n)}n\le\frac{\max_kM_k(A)}n\le\Phi(v)+2\sqrt{\frac{\log(8n)}n}.$$
构造方式：按定理 4.3 的证明随机舍入，再修正质量；失败概率 $\le1/2$，重复抽样即可。这个保证很松：要让误差 $\le10^{-3}$ 需 $n\approx10^8$，所以它只用于证明存在性。

**8.3 固定网格的二值化差距不是问题本身的 gap.** 0/1 的 $N$ 格数组恰是 $n=N/2$ 的划分，其最优值 $M(N/2)/(N/2)\ge\mu$。round 3 在 $N=2400$ 上测得：二值化后用 SA 得到 0.3983，分数值 0.3809。这比较的是 $M(1200)/1200$ 的一个上界和 $\mu_{2400}$ 的一个上界。两者差距由有限 $n$ 造成，按定理 4.3 在 $n\to\infty$ 时消失。所以 v4 取消二值化：二值化损失的是分辨率，换不来有效性。

## 9. Gap 汇总

对 evaluator 输出 $v$，记文献下界 $\mu_{\rm lb}=0.379005$：
$$\mu_{\rm lb}\ \le\ \mu\ \le\ \mu_N\ \le\ \Phi(v)\ \le\ \Phi_{\rm cert}(v).$$

| Gap | 定义 | 大小 | 处理 |
|---|---|---|---|
| G1 浮点 | $\texttt{fl}(\Phi(v))$ 与 $\Phi(v)$ 之差；质量 $\sum v=N/2$ 在浮点下未必精确 | 递归求和误差 $\lesssim (N+2)u\cdot N\cdot\Delta=2(N+2)u\approx5\times10^{-13}$（$N=2400$，$u=2^{-53}$）；质量偏差 $\delta$ 修正后分数变化 $\le2\Delta|\delta|$ | `scripts/certify_erdos_grid.py`：float64 精确转二进有理数，有理数精确修正质量，大整数精确相关，向上取整输出 $\Phi_{\rm cert}$。复核后为 0 |
| G2 网格 | $\mu_N-\mu\ge0$ | 未知；$\mu_{rN}\le\mu_N$，$\mu_N\to\mu$ | 只影响可达值，不影响上界有效性；可用 repeat 后加细继续优化 |
| G3 最优性 | $\Phi(v)-\mu$ | $\le\Phi(v)-\mu_{\rm lb}\approx1.9\times10^{-3}$ | 搜索的目标 |
| G4 松弛 | $\inf_{[0,1]}C-\inf_{\{0,1\}}C$ | $=0$（定理 5.1(d)） | 无需处理 |

## 10. 与 proof.md 的对应

| proof.md 内容 | 状态 |
|---|---|
| $L^1$ 稳定性 $\lvert C(f)-C(g)\rvert\le2\|f-g\|_1$ | 保留（命题 3.1） |
| 等宽阶梯函数的折点在 $k\Delta$，correlate 精确 | 保留并给出显式公式（引理 4.1） |
| 连续函数中心采样的 Lipschitz/模连续误差 $4\omega(1/N)$、$2L/N$ | 仍然正确，但不再需要：上界有效性不依赖"数组是某个连续函数的采样"（推论 5.2） |
| 第二阶段二值化与 $\varepsilon_N$ | 被取代：二值化不是有效性所需（第 8.3 节） |
| "$C^*_{\rm rel}\le C^*_{\rm bin}$，反向需另证" | 已证：两者相等（定理 5.1(d)） |
| 总结 3–4 条（"没有普遍定理保证……"） | 被定理 5.1 取代：分数值候选本身就是 $\mu$ 的合法上界 |

## 参考文献

- J. K. Haugland, *The minimum overlap problem revisited*, arXiv:1609.08000 (2016). §1 引述 Swinnerton-Dyer 的结果：可以用阶梯函数从上方估计 $\lim M(n)/n$。
- E. P. White, *Erdős' minimum overlap problem*, arXiv:2201.05704 (2022)。下界 0.379005。
- B. Georgiev, J. Gómez-Serrano, T. Tao, A. Z. Wagner, AlphaEvolve 数学问题集 (2025)。上界 0.380924。
- TTT-Discover (2026)。上界 0.380876，见 teorth/optimizationproblems `constants/1b.md`。
- C. McDiarmid, *On the method of bounded differences* (1989)。

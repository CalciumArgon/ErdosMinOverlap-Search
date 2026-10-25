# 连续目标与有限网格评估的误差界

> 理论更新（2026-10）：本文第二阶段二值化与"反向不等式需另证"两部分已被 `reports/problem_formulation.md` 定理 5.1 取代：分数值与二值的最优值相等，合法网格数组本身就是 μ 的严格上界。

## 结论

令连续目标（Erdős number）为
$$
C_5(h)=\sup_{s\in[-2,2]} A_h(s),\qquad
A_h(s)=\int_{D_s}h(x)\bigl(1-h(x+s)\bigr)\,dx,
$$
其中
$$
D_s=\{x\in[0,2]:x+s\in[0,2]\}.
$$
给定偶数或任意正整数 $N$，设网格宽度 $\Delta=2/N$，格子
$$
I_j=[j\Delta,(j+1)\Delta),\quad j=0,\ldots,N-1,
$$
并用每格中心值定义阶梯近似
$$
h_N(x)=h(c_j),\qquad c_j=(j+\tfrac12)\Delta,\quad x\in I_j.
$$

若 $h:[0,2]\to[0,1]$ 一致连续，定义其模连续函数
$$
\omega_h(\delta)=\sup\{|h(x)-h(y)|:x,y\in[0,2],\ |x-y|\le\delta\}.
$$
则有
$$
\boxed{\ |C_5(h)-C_5(h_N)|\le 4\,\omega_h(1/N)\ },
$$
因此 $C_5(h_N)\to C_5(h)$。但是，**一致连续本身不能推出误差为 $O(1/N)$**；它只给出由具体模连续函数决定的收敛速率。

若进一步假设 $h$ 是 Lipschitz 连续的，即存在常数 $L$ 使
$$
|h(x)-h(y)|\le L|x-y|\quad (x,y\in[0,2]),
$$
则中心点取样满足更明确的界
$$
\boxed{\ |C_5(h)-C_5(h_N)|\le \frac{2L}{N}\le\frac{4L}{N}\ },
$$
故确为 $O(1/N)$。这里误差是两个目标值之差的绝对误差；若不知道 $L$，便不能由 $N$ 单独换算成具体小数精度。

## 证明

### 1. 阶梯近似的 $L^1$ 误差

由于每个 $x\in I_j$ 与中心点 $c_j$ 的距离至多为 $\Delta/2=1/N$，有
$$
|h(x)-h_N(x)|=|h(x)-h(c_j)|\le \omega_h(1/N).
$$
在区间总长度为 2 上积分，得到
$$
\|h-h_N\|_{L^1([0,2])}
=\int_0^2|h(x)-h_N(x)|\,dx
\le 2\,\omega_h(1/N).
$$

若 $h$ 是 Lipschitz 连续的，还可直接逐格积分得到更紧的估计：
$$
\begin{aligned}
\|h-h_N\|_1
&\le \sum_{j=0}^{N-1}\int_{I_j}L|x-c_j|\,dx\\
&=N\cdot L\frac{\Delta^2}{4}
=\frac{L}{N},
\end{aligned}
$$
因为 $\Delta=2/N$。

### 2. 固定偏移下目标积分的稳定性

固定 $s\in[-2,2]$。在 $D_s$ 上加减 $h_N(x)(1-h(x+s))$，可写成
$$
\begin{aligned}
&h(x)(1-h(x+s))-h_N(x)(1-h_N(x+s))\\
&=(h(x)-h_N(x))(1-h(x+s))
+h_N(x)\bigl(h_N(x+s)-h(x+s)\bigr).
\end{aligned}
$$
因 $h,h_N\in[0,1]$，故
$$
\begin{aligned}
|A_h(s)-A_{h_N}(s)|
&\le \int_{D_s}|h(x)-h_N(x)|\,dx\\
&\quad+\int_{D_s}|h(x+s)-h_N(x+s)|\,dx\\
&\le 2\|h-h_N\|_{L^1([0,2])}.
\end{aligned}
$$
第二项作变量代换 $y=x+s$ 后，积分区间是 $[0,2]$ 的子集，因此也不超过全区间的 $L^1$ 误差。此估计对所有 $s$ 一致成立。

### 3. 对偏移取 supremum

对任意两个有界函数族 $a_s,b_s$，有
$$
|\sup_s a_s-\sup_s b_s|\le \sup_s|a_s-b_s|.
$$
应用于 $A_h(s)$ 和 $A_{h_N}(s)$，得
$$
|C_5(h)-C_5(h_N)|
\le \sup_{s\in[-2,2]}|A_h(s)-A_{h_N}(s)|
\le 2\|h-h_N\|_1.
$$
结合第一步，得到一致连续情形
$$
|C_5(h)-C_5(h_N)|\le4\omega_h(1/N)\longrightarrow0.
$$
结合 Lipschitz 情形的更紧 $L^1$ 估计，则
$$
|C_5(h)-C_5(h_N)|\le 2L/N.
$$
证毕。

## 为什么“一致连续”不等价于 $O(1/N)$

一致连续仅保证 $\omega_h(\delta)\to0$，不保证 $\omega_h(\delta)\le K\delta$。例如在 $[0,2]$ 上取
$$
h(x)=\frac12+a\left|x-1\right|^\alpha,
\qquad 0<\alpha<1,
$$
并取足够小的 $a>0$ 使 $h\in[0,1]$。该函数一致连续，但在 $x=1$ 附近只有 Hölder $\alpha$ 正则性，模连续量级为 $\delta^\alpha$，而不是 $O(\delta)$。上述一般保证因此是
$$
|C_5(h)-C_5(h_N)|\le4\omega_h(1/N),
$$
不一定是常数乘 $1/N$。若已知 Hölder 条件 $|h(x)-h(y)|\le K|x-y|^\alpha$，则可得 $O(N^{-\alpha})$。

## 与离散相关 evaluator 的关系及适用范围

当 $h_N$ 在每个等宽格子上取常数时，对网格偏移 $s=k\Delta$，
$$
A_{h_N}(k\Delta)=\Delta\sum_{i:\,0\le i,i+k<N}h_i(1-h_{i+k}),
$$
正是离散相关求和乘以 $\Delta=2/N$ 的结果。对这个等宽阶梯函数，$A_{h_N}(s)$ 关于连续偏移 $s$ 是分段线性的，其折点位于格子边界之差，也就是整数倍 $\Delta$。因此连续偏移上的最大值可在这些网格偏移处取得；完整的 `np.correlate(..., mode="full")` 枚举这些偏移，就能求出该阶梯函数的最大值（忽略浮点舍入误差）。

以上定理比较的是**给定连续函数 $h$** 与**由其格子中心采样产生的阶梯函数 $h_N$** 的连续目标值。它不自动证明：

1. 任意算法生成的数组都是某个固定连续函数的中心采样；
2. 离散搜索得到的最优值与连续问题全局最优值之间有同样的误差界；
3. 质量约束仍被精确保留。

特别地，中心取样的 $h_N$ 不一定满足 $\int_0^2h_N=1$，即使原函数满足。若评估前将数组归一化或投影到质量约束集合，归一化/投影造成的额外 $L^1$ 改变量也必须加入误差估计。只有在控制了这些额外误差、并且具有相应正则性常数时，才能将上述函数逼近界转化为受约束问题的具体保证。

所以，对于 $N=512$，若已知 $h$ 的 Lipschitz 常数为 $L$，中心点阶梯近似满足
$$
|C_5(h)-C_5(h_{512})|\le L/256.
$$
若只知道 $h$ 一致连续，则可保证差值趋于零，但不能仅凭 $N=512$ 给出数值误差上限或“保证多少位精度”。

## 指示函数（集合问题）与 $[0,1]$ 值函数（松弛问题）

如果原始对象是一个集合 $A\subset[0,2]$，其对应函数应为集合的指示函数
$$
\mathbf 1_A(x)=\begin{cases}1,&x\in A,\\0,&x\notin A.\end{cases}
$$
并且质量约束为 $|A|=\int_0^2\mathbf 1_A(x)\,dx=1$。这不等于特指有理数/无理数划分的 Dirichlet 函数：例如 $\mathbf 1_{\mathbb Q\cap[0,2]}$ 几乎处处为 $0$，积分为 $0$，不满足质量约束。一般集合的指示函数在集合边界处可能不连续，但不必处处不连续。

当前任务说明允许 $h(x)\in[0,1]$，因而允许段值为非整数的分段常数函数。这是比集合指示函数更大的可行类，可视作对集合问题的函数值松弛。定义
$$
C_{\mathrm{set}}^*=\inf_{\substack{h=\mathbf 1_A\\ |A|=1}}C_5(h),\qquad
C_{\mathrm{relax}}^*=\inf_{\substack{0\le h\le1\\ \int_0^2h=1}}C_5(h).
$$
由于集合指示函数也是 $[0,1]$ 值函数，立即有
$$
C_{\mathrm{relax}}^*\le C_{\mathrm{set}}^*.
$$
反向不等式（即两个问题最优值相等）不能仅由定义或 evaluator 的精确计算推出，需要另行证明。因此，对某个分数值候选函数精确算出 $C_5(h)$，并不自动给出集合指示函数候选的同等目标值。

不过，目标对 $L^1$ 扰动稳定。若 $f,g:[0,2]\to[0,1]$，则对每个固定 $s$，
$$
\begin{aligned}
&f(x)(1-f(x+s))-g(x)(1-g(x+s))\\
&=(f(x)-g(x))(1-f(x+s))+g(x)\bigl(g(x+s)-f(x+s)\bigr),
\end{aligned}
$$
所以使用 $0\le f,g\le1$ 并在 $D_s$ 上积分可得
$$
|A_f(s)-A_g(s)|\le 2\|f-g\|_{L^1([0,2])}.
$$
对 $s$ 取 supremum 后得到
$$
\boxed{|C_5(f)-C_5(g)|\le2\|f-g\|_{L^1([0,2])}}.
$$
因此，如果能构造一个质量正确的集合指示函数 $g=\mathbf1_A$，并证明它与分数值函数 $h$ 的 $L^1$ 距离很小，那么两者的 Erdős 目标值差异就有显式上界。关键是必须实际证明这个 $L^1$ 距离小；单有 $0\le h\le1$ 并不能保证存在这样的近似。

特别注意，前文 Lipschitz 采样定理比较的是固定的 Lipschitz 函数与其中心取样阶梯近似。一般集合的指示函数不满足 Lipschitz 条件，所以不能直接将前文的 $O(1/N)$ 误差界套用于任意集合。对边界有额外规整性的集合可以另行证明网格近似率；对任意可测集合，仅凭 $N$ 不足以给出统一误差位数。

## SimpleTES 的两阶段松弛与 ground truth 的可证明关系

本节明确区分原始二值连续问题、有限网格表示和当前代码实际评分的对象。把原始集合记作 $A\subset[0,2]$，原始二值函数记作
$$
h_{\mathrm{bin}}=\mathbf 1_A,\qquad |A|=1,
$$
其目标值为 $C_5(h_{\mathrm{bin}})$。把代码允许的分数值函数记作 $h_{\mathrm{rel}}$；对旧版 $N$ 格数组，它对应的函数是
$$
h_{N,\mathrm{rel}}(x)=v_i\quad(x\in I_i),\qquad v_i\in[0,1],\qquad \Delta=2/N.
$$
如果满足质量约束，则 $\Delta\sum_{i=0}^{N-1}v_i=1$，等价于 $\sum_i v_i=N/2$。这两个约束描述的是松弛后的分数值阶梯函数，不是二值集合指示函数。

### 第一阶段：连续二值函数到有限网格

若网格 evaluator 对数组完整计算离散相关，则它实际上是在评估 $h_{N,\mathrm{rel}}$ 这个有限阶梯函数，而不是对另一个未知连续函数作数值求积。对等宽阶梯函数，移位目标在相邻网格移位之间为线性函数，折点在 $k\Delta$；因此在精确算术下，对所有 $k$ 的相关计算给出的是该阶梯函数连续移位 supremum 的精确值。这里不存在额外的“移位只采样了格点，所以漏掉阶梯函数最大值”的误差；浮点舍入误差另计。

但若想把一个给定的二值集合 $A$ 通过网格取样/量化成二值阶梯函数 $h_{N,\mathrm{bin}}$，任意可测集合的边界可任意复杂，单凭 $N$ 无法保证该网格函数与 $\mathbf1_A$ 的 $L^1$ 距离小。因此，**对任意可测集合，第一阶段没有只依赖 $N$ 的统一误差上界**。若 $A$ 是 $r$ 个区间的并（忽略端点），按每格中心取样生成原始二值阶梯近似 $\widetilde h_{N,\mathrm{bin}}$，只有含有边界点的格子可能取错；边界至多 $2r$ 个，所以
$$
\|\widetilde h_{N,\mathrm{bin}}-\mathbf1_A\|_1\le 2r\Delta=\frac{4r}{N}.
$$
由 $L^1$ 稳定性，进一步有
$$
|C_5(\widetilde h_{N,\mathrm{bin}})-C_5(\mathbf1_A)|\le\frac{8r}{N}.
$$
但中心取样后的二值数组未必恰有 $N/2$ 个 1，故未必满足质量约束；上述只是函数逼近界。若要得到可行的有限网格二值候选，还需精确修正质量，并把修正造成的额外 $L^1$ 误差计入。该有限区间并的条件性界不适用于任意可测集合，也不直接适用于分数值数组。

### 第二阶段：分数值阶梯函数到二值阶梯函数

对 $h_{N,\mathrm{rel}}$ 而言，仅有 $0\le v_i\le1$ 和 $\sum_i v_i=N/2$ 并不能保证它接近某个质量为 1 的二值函数。事实上，若 $h_{N,\mathrm{rel}}\equiv1/2$，则对任意二值函数 $g=\mathbf1_B$ 且 $|B|=1$，都有
$$
\|h_{N,\mathrm{rel}}-g\|_1=1.
$$
所以不存在仅由 $N$ 推出的、趋于零的通用 $L^1$ 二值化误差界。若指定一个二值化规则 $Q$，并能另外证明
$$
\|h_{N,\mathrm{rel}}-Q(h_{N,\mathrm{rel}})\|_1\le\varepsilon_N,
$$
其中 $Q(h_{N,\mathrm{rel}})$ 满足二值性和质量约束，那么唯一可直接套用的目标保证是
$$
|C_5(h_{N,\mathrm{rel}})-C_5(Q(h_{N,\mathrm{rel}}))|\le2\varepsilon_N.
$$
若直接对一个连续 Lipschitz 函数采样成网格值，得到第一阶段阶梯函数 $h_{N,\mathrm{rel}}$，则
$$
\|h_{\mathrm{rel}}-h_{N,\mathrm{rel}}\|_1\le L/N.
$$
现在解释第二阶段的 $\varepsilon_N$：它不是另一个预先已知的常数，也不是由 $N$ 自动决定的误差，而是对一个**指定的二值化规则** $Q_N$ 所作的假设/证明目标。令
$$
h_{N,\mathrm{bin}}=Q_N(h_{N,\mathrm{rel}}),\qquad h_{N,\mathrm{bin}}=\mathbf1_{A_N},\qquad |A_N|=1,
$$
并要求证明
$$
\varepsilon_N\ge \|h_{N,\mathrm{rel}}-h_{N,\mathrm{bin}}\|_{L^1([0,2])}.
$$
这个距离是两函数在整个区间上的绝对差积分；它量化分数值网格函数被二值化后改动了多少“质量”。若 $h_{N,\mathrm{rel}}$ 和 $h_{N,\mathrm{bin}}$ 都质量正确，则 $\int(h_{N,\mathrm{rel}}-h_{N,\mathrm{bin}})=0$，故
$$
\varepsilon_N\ge\|h_{N,\mathrm{rel}}-h_{N,\mathrm{bin}}\|_1
=2\int_0^2\bigl(h_{N,\mathrm{rel}}(x)-h_{N,\mathrm{bin}}(x)\bigr)_+\,dx.
$$
由 $L^1$ 稳定性，第二阶段的目标值改变量最多是 $2\varepsilon_N$。所以从连续松弛函数，经网格采样，再经二值化，完整的两阶段误差保证是
$$
\boxed{\left|C_5(h_{\mathrm{rel}})-C_5(h_{N,\mathrm{bin}})\right|
\le \frac{2L}{N}+2\varepsilon_N.}
$$
这里第一项来自连续 Lipschitz 函数到网格阶梯函数，第二项来自网格分数值函数到指定二值函数。若只比较 evaluator 评分的 $h_{N,\mathrm{rel}}$ 与其二值化结果，则去掉第一项：
$$
\boxed{\left|C_5(h_{N,\mathrm{rel}})-C_5(h_{N,\mathrm{bin}})\right|\le2\varepsilon_N.}
$$
这些是条件性保证：要得到数值误差界，必须构造 $Q_N$ 并实际证明 $\varepsilon_N$ 的上界。若 SimpleTES 只输出分数值数组，没有连续 Lipschitz 原函数，也没有二值化及其 $L^1$ 误差证明，则不能把 $2L/N+2\varepsilon_N$ 报作它当前搜索解已经满足的误差界。

例如，若二值化采用“取值最高的 $N/2$ 个格子置为 1，其余置为 0”（假设 $N$ 为偶数并按规则处理并列值），则这个规则保证二值数组质量正确，但 $\varepsilon_N$ 必须按实际数组计算：
$$
\varepsilon_N=\Delta\sum_{i=0}^{N-1}|v_i-b_i|,
\qquad b_i\in\{0,1\},\quad \sum_i b_i=N/2.
$$
该量可能很大；例如所有 $v_i=1/2$ 时，对任何质量正确的二值数组都有 $\varepsilon_N=1$，所以不能仅凭质量正确或 $N$ 大就断言二值化误差趋零。

### 松弛最优值与二值最优值

定义连续分数值问题与连续二值问题的全局最优值 $C_{\mathrm{rel}}^*$、$C_{\mathrm{bin}}^*$。可行类包含关系给出
$$
C_{\mathrm{rel}}^*\le C_{\mathrm{bin}}^*.
$$
这是关于两个**全局最优值**的弱不等式，并非严格不等式，也不是“某个松弛候选值大于某个二值候选值”。对一个具体 $h_{N,\mathrm{rel}}$，它的目标值既不自动上界 $C_{\mathrm{bin}}^*$，也不自动低于或高于某个由它二值化得到的候选。若有满足质量的二值函数 $h_{\mathrm{bin}}$，且证得 $C_5(h_{\mathrm{bin}})\le C_5(h_{N,\mathrm{rel}})$，那么 $h_{\mathrm{bin}}$ 才给出二值问题的候选上界；可行类包含关系本身不提供这样的候选构造。

### 总结：当前可声称与不可声称的结论

$$
\boxed{\left|C_5(h_{\mathrm{rel}})-C_5(h_{N,\mathrm{bin}})\right|\le \frac{2L}{N}+2\varepsilon_N}
$$

1. 对 evaluator 实际评分的有限阶梯函数，相关计算可精确给出该阶梯函数的连续移位目标值（忽略浮点舍入误差）。
2. 对固定连续且有已知正则性常数的 $h_{\mathrm{rel}}$，可用前文的模连续/Lipschitz 界控制它与特定网格近似之间的误差；这需要该候选确实由该 $h_{\mathrm{rel}}$ 采样得到，并计入质量投影的影响。
3. 对任意二值 ground truth 集合与代码生成的任意分数值阶梯候选，目前没有仅依赖 $N$ 的统一误差界；也没有普遍定理保证能从该候选恢复一个目标值不更大的质量正确二值函数。
4. 因此，SimpleTES 找到的分数值阶梯候选是松弛问题的有效可评估候选，但要把它转化为原始二值集合问题的误差保证，必须额外给出二值化/逼近构造和相应证明，或证明两种全局最优值相等。

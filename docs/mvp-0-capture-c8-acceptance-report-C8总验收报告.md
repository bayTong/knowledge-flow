# MVP-0 捕获内核 C8 本地总验收报告

> 验收日期：2026-09-29<br>
> 验收类型：本地 Windows 总验收<br>
> 被验收基线：`896c64ce678e26077f32163375c812043244c6e6`（`896c64c`）<br>
> 本地技术结论：**通过**<br>
> 版本化状态：已由独立提交 `63f3a3d` 封存并推送<br>
> 远端门禁：[Windows CI 运行 `36544619016`](https://github.com/bayTong/knowledge-flow/actions/runs/36544619016) 在精确提交 `63f3a3d` 上成功<br>
> 后续状态：MVP-0 单机单用户文本捕获内核为 `Implemented`；适用范围以设计权威登记为准

## 1. 结论

C8 本地总验收已证明：当前 MVP-0 捕获内核的四个文本操作、受限 CLI、初始化、业务事务恢复、派生状态重建和 Store 迁移，在本机 Windows 10 / Python 3.13 环境中通过现有完整自动化矩阵；真实 4 MiB/64 MiB 边界、真实多进程竞争、进程强制终止后的新进程恢复、临时非 editable 安装与 console script 发现也全部通过。

本轮没有修改 `src/`、公共 Python API、CLI 线协议、Store schema、事务提交点或错误优先级。验收前后均未创建默认机器配置或生产 Capture Store；测试只使用测试持有的临时目录。

因此，本地验收出具时的证据支持把 **MVP-0 捕获内核实现**评定为 `Implemented` 候选，但不支持评定为 `Effective`：Windows 目录元数据 flush 在当前实现中明确为 `unsupported`，突然断电、磁盘控制器缓存、文件系统损坏、第三方长期占用和真实生产数据运行均未被证明。出具时 `Implemented` 尚未进入正式状态词表；后续远端门禁与状态同步见第 9 节。

## 2. 验收边界

本轮包含：

- 全部单元、集成、并发、故障、恢复、迁移和维护脚本测试。
- 真实 4 MiB/64 MiB 捕获、追加、列表和读取往返。
- 两个真实进程的同 key/不同 key 竞争和 Windows 内核锁释放。
- `os._exit()` 故障点与新进程恢复。
- 安装包元数据、console script、临时非 editable 安装和 README 使用边界。
- 公共错误码/警告码与操作契约表的一致性。
- 仓库卫生、生产路径前后快照和文档一致性。

本轮不包含：

- 创建 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`。
- 创建或写入 `E:\KnowledgeFlowData\capture-store`。
- 真实断电、拔盘、磁盘控制器缓存欺骗或破坏性文件系统测试。
- GBrain、LLM、RAG、知识图谱、路由、SOP、UI、网络服务或可信 Wiki 写入。
- commit、push、发布或部署。

## 3. 环境与基线

| 项目 | 实际值 |
|---|---|
| 操作系统 | Windows 10 Pro 22H2，build 19045.6093 |
| Python | CPython 3.13.5，64-bit |
| 本地解释器 | `.venv\Scripts\python.exe` |
| 包 | `knowledgeflow-capture 0.1.0.dev0` |
| 运行时依赖 | `PyYAML 6.0.3` |
| 声明的构建后端 | `setuptools==80.9.0` / `setuptools.build_meta` |
| Git 分支 | `main`，验收开始时相对 `origin/main` ahead 1 |
| 被验收 HEAD | `896c64c docs(status): 记录 C7V 远端门禁并推进至 C8` |

本地 `.venv` 没有独立安装 `setuptools` 分发包；CLI-25 的隔离安装测试按契约从受控的 system-site 构建环境继承后端并禁用网络，仍然通过。远端 Windows CI 已在 C7V 可移植性修复中显式安装精确的 `setuptools==80.9.0`；C8 提交的后续远端复验结果见第 9 节。

## 4. 自动化结果

### 4.1 C8 定向矩阵

命令运行了故障注入、真实边界、读取验收、追加验收、派生状态重建、迁移和 CLI 验收共 41 项测试。

| 结果 | 数量 | 用时 |
|---|---:|---:|
| 通过 | 41 | 89.201 s |
| 失败 | 0 | — |
| 跳过 | 0 | — |

定向集合实际覆盖：

- 初始化、`capture_text` 与 `append_capture_version` 的全部进程退出故障点。
- 真实 4 MiB 和 64 MiB 边界、有界流读取及默认 10 秒锁等待。
- 双进程同 key 收敛、不同 key 的 CAS 竞争。
- 读取、分页、派生状态重建和 A→B Store 迁移。
- 尾随 byte 零提交、stdout 故障、临时安装入口和真实 CLI 双进程竞争。

### 4.2 两轮完整测试

| 模式 | 命令 | 结果 | 用时 |
|---|---|---|---:|
| 普通 | `python -m unittest discover -s tests -p "test_*.py" -v` | 305/305 通过 | 134.157 s |
| 严格资源警告 | `python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v` | 305/305 通过 | 134.296 s |

两轮均无失败、错误或跳过；严格轮没有产生未关闭文件、目录或子进程资源警告。

### 4.3 文档收口后的提交态复验

新增报告尚未进入正式 Git 索引时，直接重跑 305 项得到 304 项通过、1 项失败；唯一失败是 `test_cli_current_repository_passes_as_json`，原因正是文档护栏拒绝 README 指向未跟踪的项目文档。该结果证明护栏按设计工作，不是业务代码回归，也没有通过放宽规则绕过。

随后复制正式索引到系统临时文件，只在临时索引中为新报告加入一个跟踪条目，并在完全相同的工作树上重新运行全量测试；正式索引始终未改变：

| 模式 | 结果 | 用时 |
|---|---|---:|
| 提交态模拟，普通 | 305/305 通过 | 139.003 s |
| 提交态模拟，严格 `ResourceWarning` | 305/305 通过 | 136.055 s |

这证明当前 diff 在形成包含新报告的真实提交后满足 305 项门禁；在实际 `git add`/commit 前，直接运行文档护栏继续拒绝未跟踪报告是正确行为。

### 4.4 工程门禁

| 检查 | 结果 |
|---|---|
| `python -m compileall -q src tests scripts` | 通过 |
| `python -m pip check` | 通过；`No broken requirements found.` |
| `python scripts/doc-check.py`（文档编辑前基线） | 通过：32 个现行 Markdown、6 个路由目标、59 个结构树文件 |
| `git diff --check`（文档编辑前基线） | 通过 |
| C8 报告和路由变更后的文档护栏 | 通过（临时 Git 索引模拟提交态）：33 个现行 Markdown、7 个路由目标、60 个结构树文件 |
| 文档/维护脚本回归 | 15/15 通过，1.217 s |

## 5. 安装、入口与公共契约复核

### 5.1 安装与命令入口

- 安装分发名和版本为 `knowledgeflow-capture 0.1.0.dev0`。
- console entry 精确映射为 `knowledgeflow-capture = knowledgeflow_capture.cli:main`。
- 当前环境存在 `Scripts/knowledgeflow-capture.exe`。
- 发布记录只包含包元数据、许可证、editable 路径文件和命令入口，没有把 `tests/` 或测试 support 安装为生产接口。
- CLI-25 在测试持有的临时源码副本和临时 venv 中完成禁网、非 editable 安装，并成功发现 console script。

### 5.2 README 与错误表

C8 审计发现并在本批文档中收口两项说明缺口：

1. 双语 README 原先只说明后续建设顺序，没有给出已安装 CLI 的机器协议调用边界；现补充四个命令、stdin/stdout 帧、0/2/70 退出码及“不会自动初始化生产 Store”的说明。
2. 四操作契约的公共表原先没有显式列出管理操作专用的 `config_store_conflict`，也没有说明已在公共模型中保留但当前四操作不产生的 `outbox_needs_rebuild`；现补齐其适用范围，未改变代码或运行时行为。
3. 新验收报告进入双语 README 路由后，同步扩展 `doc-check.py` 的固定路由白名单；既有 15 项脚本回归全部通过，检查强度没有降低。

公共错误消息仍由 `tests.capture.unit.test_errors.ErrorModelTest.test_all_public_error_messages_are_exact_contract_values` 精确校验；CLI 不翻译或重写核心错误码、warning、`saved` 或 `commit_state`。

## 6. 耐久、恢复与平台结论

| 项目 | 本轮证据 | 结论 |
|---|---|---|
| 文件写入 | flush、`fsync`、关闭后回读和严格验证测试通过 | 已证明应用级写入顺序 |
| 无覆盖提交 | 文件/目录同卷 rename、目标竞争和三态现场测试通过 | 已证明受控进程环境中的无覆盖语义 |
| Windows 内核锁 | 持锁进程终止后新进程取得同一锁的测试通过 | 已证明进程终止释放内核锁 |
| 业务事务恢复 | capture/append 多个 `os._exit()` 点由新进程恢复 | 已证明受控进程崩溃恢复 |
| 重建与迁移 | REC、MIG 全矩阵及中断重试通过 | 已证明临时 Store 中的恢复/迁移语义 |
| 目录元数据 flush | 本机实际探针：`unsupported` | 不得宣称目录项已抗断电持久化 |
| 突然断电/控制器缓存 | 未执行破坏性实机试验 | 未证明 |

这里的“强制终止通过”只代表操作系统仍运行时的进程崩溃恢复；不能外推为突然掉电后绝对不丢数据。

## 7. 仓库与真实路径卫生

验收前后结果一致：

- `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`：不存在。
- `E:\KnowledgeFlowData\capture-store`：不存在。
- Git 跟踪文件中没有 `.venv/`、机器配置、真实 `items/`、`journal/` 或 `.staging/` 运行时内容。
- `tests/capture/fixtures/capture-store-v1.yaml` 是受控 Manifest golden fixture，不是真实 Store 或用户 Capture。
- `.venv/` 由 `.gitignore` 忽略。
- 测试结束后没有出现新的可枚举未跟踪文件。

本地工作区存在验收前即有的 `.probe-new/` 下四个目录和 `tmpu5uxhkuy/`，Git 枚举时报告 ACL `Permission denied`。它们不在 Git 索引中，C8 没有读取、删除或修改它们；由于无法递归读取，本报告不能证明这些本机目录内部为空。该限制不影响被跟踪仓库和临时 Store 测试结论，但应作为独立本机清理/ACL 任务处理，不能混入 C8 功能提交。

## 8. 未证明项和已知限制

以下内容不因 C8 本地通过而获得保证：

- 突然断电、拔盘、控制器虚报 flush、文件系统或介质损坏。
- 杀毒软件、同步盘、备份程序长期持有文件或极端磁盘压力。
- 多用户、网络文件系统、UNC、Linux/macOS 或非 NTFS 文件系统。
- 真实生产 Capture Store 的长期运行、备份、恢复、容量和人工使用体验。
- 捕获之外的人工路由、语义提炼、RAG、候选图谱、GBrain 镜像或可信 Wiki 写入。
- 对知识语义召回率、正确率或“无遗漏”的任何承诺。

## 9. 状态建议与后续门禁

本地技术验收结论是：**C8 本地矩阵通过，MVP-0 捕获内核达到 `Implemented` 候选条件。**

本报告最初出具时，提交、远端门禁与正式状态确认尚未完成；上述本地结论因此只称 `Implemented` 候选。后续闭合记录如下：

1. 用户授权将本地证据单独提交，`63f3a3d` 已封存本报告并推送至 `origin/main`。
2. [Windows CI 运行 `36544619016`](https://github.com/bayTong/knowledge-flow/actions/runs/36544619016) 在该精确提交上成功；安装、普通与严格 `ResourceWarning` 全量测试、编译、依赖和文档检查步骤均成功。
3. 用户于 2026-09-29 指示通过后单独同步 C8 状态锚点。设计权威登记据此新增 `Implemented`，并将其限定于 MVP-0 单机单用户文本捕获内核；下一独立门禁为 P0 的生产初始化与最小收件箱 dogfood 规划及明确授权。

真实断电与生产运行证据尚未形成，故不使用 `Effective`，也不宣称生产就绪。

# 第 1 天复盘：建包、镜像与飞书进程的启动

> 依据：历史提交 `31aa577`、`09e942f`、`27b2200`；当前仓库 `cec5ffe` 加工作区中的飞书适配改动。历史事实和当前行为分开表述。2026-10-14 检查时 Docker 引擎未运行，因此本页是源码链路核对，没有声称做过实时容器验证。

## 本节要解决的工程问题

把 Python Agent 做成可导入、可安装、可在 Linux 容器内稳定启动的程序，并让飞书适配入口复用核心代码。

## 从开发顺序看设计

1. `31aa577` 先建立 `core/pyproject.toml`：当时项目名还是 `project-k`，声明 Python 3.14、Pydantic AI、Pydantic、配置、日志等依赖；核心业务代码还没有成型。这个提交能证明项目骨架先于 Agent 功能，不能证明作者已完成可用 Agent。最初的 `[tool.pdm] distribution = false` 也不等于当前已发布可安装包。
2. `0b7aecb` 增加 BashSession 的第一个实现，并加入 AnyIO 依赖、把 `distribution` 改成 `true`。Shell 的源码设计留到第 2 天精读。
3. `09e942f` 才出现第一版 Dockerfile：以 Python 3.14 slim 镜像为基础，加 Bash、Git、网络工具、`uv` 等。入口脚本负责容器用户与挂载工作区的准备；那时还没有今天的飞书服务。
4. `27b2200` 把容器的长驻进程管理改成 Supervisor、sshd、cron。今天的 Supervisor 也负责启动 `/home/k/start.sh`，但具体文件已继续演进，不应把早期版本与当前版本混说。

这种顺序的工程含义是：先有项目骨架，再验证 Shell 会话，然后把可用的 Linux 运行环境装进镜像，最后发展成 Agent 服务。作者主观动机未在提交中完整说明，这里是基于代码顺序的设计分析。

### 逐段读最早的 `pyproject.toml`

在 `31aa577` 里，核心字段是：

```toml
[project]
name = "project-k"
dependencies = ["pydantic-ai>=1.56.0", "pydantic>=2.12.5", "pydantic-settings>=2.12.0", "python-dotenv>=1.2.1", "logfire>=4.22.0", "rich>=14.3.2"]
requires-python = "==3.14.*"

[tool.pdm]
distribution = false
```

`[project]` 描述 Python 项目及运行依赖；`[dependency-groups].dev` 中的 pytest、ruff、ty 是开发检查工具。初始 `core/src/k/agent/main.py` 只有 `print("hello")`，因此该提交仅是项目骨架。尤其注意 `distribution = false`：不能把它描述成已可发布的完整包。

到 `0b7aecb` 增加 BashSession 时，同一次提交把 `anyio>=4.12.1` 加入运行依赖，并将 `distribution` 改成 `true`，同时建立 `k/__init__.py` 等包结构。这是明确的**需求推动依赖和打包能力增长**的证据。Pydantic AI、Pydantic、配置和日志依赖在初始阶段存在，不等于那些功能当时已经实现。

### 逐段读早期 Docker 提交

`09e942f` 的 Dockerfile 以 `python:3.14-slim-bookworm` 为基础，安装 Bash、Git、curl、`uv` 等；复制的主要是 `docker-entrypoint.sh`。它**没有把 `core/` 复制并安装进镜像**，所以当时更像一台可控的基础 Linux 工作环境，而不是打包好的飞书 Agent 服务。配套 `scripts/docker-start.sh` 接受宿主机工作区路径，并用 `-v <host_workspace>:/home/k` 挂载，且把宿主机 UID/GID 传入容器。

`27b2200` 的 diff 移除了原先的 `tini/gosu/supercronic` 方案，加入 `supervisor`、`openssh-server`、系统 `cron`，将 `supervisord.conf` 复制进镜像，并在启动脚本中映射宿主机端口到容器 22 端口。可以从提交中确认**进程管理方式确实改变**；“为了以后远程工具调用方便”只是依据 SSH 配置作出的合理推断，面试时应说成推断。

### 当前 Dockerfile 的每一层

```dockerfile
FROM python:3.14-slim-trixie
RUN ... apt-get install ... bash git openssh-server supervisor ...
RUN pip install --no-cache-dir uv ast-grep-cli
COPY core/ /core/
COPY collections/ /collections/
COPY shell-session-manager/ /shell-session-manager/
RUN uv pip install --system --no-cache -e /core -e /collections -e /shell-session-manager typer
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
```

`FROM` 选 Python 与 Debian 基础系统；`RUN` 在**构建时**安装 Linux 命令和 Python 安装工具；`COPY` 把本地源码放进镜像；`uv pip install --system -e` 把三个项目安装到系统 Python 环境，`-e` 为 editable 安装，导入时会指向安装路径上的源码；`ENTRYPOINT` 是容器启动时首先执行的程序。`WORKDIR /` 是默认工作目录，不是持久工作区。`PYTHONDONTWRITEBYTECODE=1` 避免写 `.pyc`，`PYTHONUNBUFFERED=1` 让 Python 输出更及时进入容器日志。

当前 Compose 的 `build.context: ..` 从 `docker/` 指到仓库根目录，所以 Dockerfile 的 `COPY core/` 才能读到仓库里的 `core/`。Compose **运行时**又挂载 `../core:/core` 和 `../collections:/collections`，覆盖镜像内同位置的源码，便于本地开发。`shell-session-manager` 在当前 Compose 中没有对应源码挂载；修改它后不能照搬“改源码就直接生效”的结论，通常要重建镜像。

## 当前仓库的五层结构

| 层 | 当前源码证据 | 承担的事 |
| --- | --- | --- |
| Python 核心包 | [`core/pyproject.toml`](../../core/pyproject.toml) | 安装 `kapybara` 包；`kapy` 命令映射 `k.agent.core.run:cli` |
| 入口扩展包 | [`collections/pyproject.toml`](../../collections/pyproject.toml) | 安装 `kapy-collections`，包含飞书 starter 依赖 |
| 镜像 | [`docker/basic-os/Dockerfile`](../../docker/basic-os/Dockerfile) | 基于 `python:3.14-slim-trixie`，装 Linux 包；复制并以 editable 方式安装三个本地包 |
| 容器定义 | [`docker/docker-compose.yaml`](../../docker/docker-compose.yaml) | 构建镜像、设置 `PUID/PGID`、声明重启和宿主机目录挂载 |
| 进程启动 | [`docker-entrypoint.sh`](../../docker/basic-os/docker-entrypoint.sh)、[`supervisord.conf`](../../docker/basic-os/supervisord.conf)、[`start.feishu.example.sh`](../../data/fs/start.feishu.example.sh) | 初始化运行身份，启动 Supervisor，再以 `k` 用户启动飞书 Python 进程 |

镜像是文件系统与依赖模板；容器是运行该模板的实例；挂载把宿主机目录映射进容器；进程则是真正在容器里运行的程序。今天的 Dockerfile 将 `/core`、`/collections`、`/shell-session-manager` 安装到 Python 环境；Compose 又把前两者的宿主机源码挂回同一路径，所以日常改 Python 源码通常可由运行环境直接看到，改镜像依赖则需要重新构建。

## 路径与进程图

```mermaid
flowchart LR
    A[Windows: D:/Myproject/agent/Kapybara] --> B[Docker Compose]
    B --> C[Linux 容器 basic-os]
    A -->|data/fs 卷挂载| H[/home/k]
    A -->|core 卷挂载| K[/core]
    A -->|collections 卷挂载| L[/collections]
    C --> I[docker-entrypoint.sh]
    I --> S[supervisord]
    S --> ST[/home/k/start.sh]
    ST --> F[python -m kapy_collections.starters.feishu]
    F --> W[飞书 WebSocket 长连接]
    F --> M[收到合格消息后调用 agent_run]
```

| 宿主机路径（仓库内） | 容器路径 | 用途 |
| --- | --- | --- |
| `data/fs` | `/home/k` | 工作区、`.env`、`.kapybara/config.toml`、长期数据 |
| `core` | `/core` | Agent 核心源码 |
| `collections` | `/collections` | 飞书适配入口源码 |
| `data/crontabs` | `/var/spool/cron/crontabs` | cron 配置持久化 |

## 一次启动的调用链

`docker compose` 依据 Compose 文件创建容器 → Dockerfile 指定的 `docker-entrypoint.sh` 以初始权限准备用户、SSH key 和 cron 目录 → entrypoint `exec supervisord` → Supervisor 的 `[program:start]` 以 `k` 用户运行 `/home/k/start.sh` → 脚本读取 `/home/k/.env` 并给出 `K_CONFIG_BASE=/home/k/.kapybara` 的默认值 → `python -m kapy_collections.starters.feishu` 进入 [`__main__.py`](../../collections/src/kapy_collections/starters/feishu/__main__.py) → [`cli.py`](../../collections/src/kapy_collections/starters/feishu/cli.py) 读取飞书凭据与白名单 → [`runner.run_forever`](../../collections/src/kapy_collections/starters/feishu/runner.py) 初始化配置、模型、文件记忆存储和长连接。

把这条链路逐段拆开：

1. **Compose 创建容器**：`docker/docker-compose.yaml` 的服务名是 `basic-os`。`PUID` 与 `PGID` 使用 `${VAR:?错误信息}` 语法，因此缺失时 Compose 配置阶段就会报错。`restart: unless-stopped` 针对整个容器；它和 Supervisor 对单个子进程的 `autorestart=true` 是两层不同的重启机制。
2. **entrypoint 初始化身份**：脚本要求最初以 root 进入，因为要修改 `/etc/passwd`、`/etc/group`、SSH key 和 crontab 权限。先检查 `PUID/PGID` 非空、是数字且非 0；再 `export WORKSPACE=/home/k`、`HOME=/home/k`。随后验证 `/home/k` 是实际挂载点，而不只是镜像里碰巧有这个目录。
3. **entrypoint 准备环境**：`ensure_group_for_pgid`、`ensure_user_for_puid` 将容器用户对齐到指定 UID/GID；`ensure_user_ssh_keypair`/`ensure_user_authorized_key` 准备 SSH；`ensure_crontab_spool` 修正 cron 挂载目录权限。最后 `exec /usr/bin/supervisord -n ...`，`exec` 会用 Supervisor 替换当前 shell 进程。
4. **Supervisor 启动应用**：`[program:start]` 的 `command=/home/k/start.sh`、`user=k` 表明飞书服务以普通用户运行。配置里还管理 sshd、cron、浏览器服务。Supervisor 常驻并监控子进程；飞书进程退出后，`autorestart=true` 会尝试重启它。
5. **start.sh 整理环境**：`set -euo pipefail` 让脚本遇到常见错误及时停止；`set -a` 使随后读取的 `.env` 变量自动导出到子进程。`sed 's/\r$//'` 只去掉 Windows CRLF 的行尾 `\r`，便于在 Linux shell 中 source。脚本再以 `exec env K_CONFIG_BASE=... python -m ...` 启动 Python；`exec` 表示不再保留一层无必要的 shell 进程。
6. **Python 入口初始化**：`__main__.py` 调用 `cli()`，后者用 `anyio.run(main)` 进入异步程序。`main` 从环境变量取得 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_ALLOWED_OPEN_IDS` 并交给 `run_forever`。`run_forever` 实例化 `Config()`、模型、`FolderMemoryStore` 和飞书 SDK channel，注册消息回调，最后 `await channel.connect()` 保持长连接。

这时**飞书适配进程已经常驻**，但还没有处理某条用户消息。收到符合条件的消息后才会调用 `agent_run`。模型 API 可以在容器外；Agent 的 Python 编排进程在容器内。按当前默认配置，Shell 执行是本地模式；若配置了 SSH 用户与地址，则可变成远程执行模式，细节留到第 3 天。

## 两层配置及一次旧故障

[`Config`](../../core/src/k/config.py) 使用 `K_` 环境变量前缀。`K_CONFIG_BASE` 指向 `.kapybara` **目录本身**；它的默认值是 `~/.kapybara`。飞书启动脚本将其设为 `/home/k/.kapybara`，避免进程以错误的 HOME 查找 `/root/.kapybara/config.toml`。

`<config_base>/config.toml` 是另一层配置，提供模型 provider、model name 和相关 API 配置；[`resolve_cli_model`](../../core/src/k/agent/core/cli_runtime.py) 在飞书服务启动时读取。飞书 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_ALLOWED_OPEN_IDS` 来自环境变量，由飞书 CLI 读取。记忆根目录位于 `<config_base>/memories`。

`Config` 的核心源码可以简化为：

```python
model_config = SettingsConfigDict(env_prefix="K_")
config_base: Path = Path("~/.kapybara")
ssh_user: str | None = None
ssh_addr: str | None = None
```

`BaseSettings` 根据 `K_` 前缀将 `K_CONFIG_BASE` 映射到 `config_base`；路径验证器把 `~` 展开、转成绝对路径。`ssh_user`/`ssh_addr` 都为空时，后续 Shell 走本地模式；同时设置才走 SSH 模式。飞书入口在 `run_forever` 中创建 `Config()` 后，再由 `resolve_cli_model` 读取 `config_base/config.toml`；如果文件缺失，程序在建立飞书长连接前就可能失败。

因此，过去的 `Expected config file at /root/.kapybara/config.toml` 是路径/运行身份配置错误；排查顺序应从 `K_CONFIG_BASE`、HOME、用户和挂载看起，而不是先怀疑模型本身。

当时使用的 `docker compose run --entrypoint kapy ...` 覆盖了镜像的正常 entrypoint，也没有经过 `/home/k/start.sh`。如果没有额外提供 `K_CONFIG_BASE`，默认 `~/.kapybara` 会随该命令实际运行用户的 HOME 解析；报错中的 `/root` 正是这一路径的证据。显式传 `-e K_CONFIG_BASE=/home/k/.kapybara` 修复了配置查找位置。

## 面试版 90 秒说明

“Kapybara 的核心是 Python 包，负责 Agent、工具和记忆；飞书入口位于独立的 collections 包。项目先建立包和依赖，再用 Docker 固定 Python 与 Linux 工具环境。现在 Compose 将工作区挂到容器 `/home/k`，把核心和入口源码挂到 `/core`、`/collections`。容器启动后由 entrypoint 准备运行用户，Supervisor 以普通用户启动飞书进程。飞书进程通过长连接收消息，符合条件时才调用核心 `agent_run`。因此 Agent 编排与 Shell 工具主要运行在 Linux 容器内，模型服务通过配置的 provider 调用。`K_CONFIG_BASE` 决定配置和记忆目录，是排查启动错误的关键。”

## 可继续深挖的点

- 第 2 天：BashSession 怎样保留进程并持续读取 stdout/stderr。
- 第 3 天：本地 PTY 与 SSH 两种命令执行路径的具体实现。
- 后续：镜像中的 editable 安装与 Compose 源码挂载在不同部署场景下的取舍。

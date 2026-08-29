# 1. 基础环境：锁定精确版本 + 国内镜像加速 (使用 slim 版本减小体积)
FROM m.daocloud.io/docker.io/library/python:3.11.9-slim

# 2. 系统设置：统一时区与编码
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo '$TZ' > /etc/timezone
ENV LANG=C.UTF-8
# 让 Python 日志实时输出，不缓存
ENV PYTHONUNBUFFERED=1

# 3. 设定工作目录
WORKDIR /app
VOLUME ["/app/data"]
# 4. 【缓存优化策略】先只拷贝环境配置文件
COPY packages.txt requirements.txt ./

# 5. 替换 apt 源 -> 安装 dos2unix -> 批量安装系统依赖 -> 清理垃圾减小体积
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y dos2unix && \
    xargs -a packages.txt apt-get install --no-install-recommends -y && \
    rm -rf /var/lib/apt/lists/*

# 6. 配置 pip 换源并安装 Python 依赖
RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple && \
    pip install --no-cache-dir -r requirements.txt

# 7. 依赖全部装完后，再拷贝你的业务代码 (这样改代码不用重新下载包)
COPY . .

# 8. 权限与跨平台处理：找到所有 sh 脚本并转换格式，赋予执行权限
RUN find . -type f -name "*.sh" | xargs dos2unix && \
    chmod +x *.sh

# 9. 启动你的主程序 (这里以 FastAPI 为例)
CMD ["python", "run_web_api.py"]
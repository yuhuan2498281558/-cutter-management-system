FROM registry.cn-zhangjiakou.aliyuncs.com/dvadmin-pro/dvadmin3-base-backend:latest
WORKDIR /backend
COPY ./backend/ .
RUN ls ./conf/
RUN python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt
CMD ["bash", "/backend/docker_start.sh"]

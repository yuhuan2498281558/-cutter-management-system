cur_path=`pwd`
docker rm mysql
# docker pull mysql:5.7
# docker pull mysql:5.5
if [ -z "${MYSQL_ROOT_PASSWORD:-}" ]; then
  echo "MYSQL_ROOT_PASSWORD must be set in the environment" >&2
  exit 1
fi
docker run -p 3306:3306 --privileged=true --name mysql -v "$cur_path/logs:/logs" -v "$cur_path/data:/var/lib/mysql" -v "$cur_path/conf.d/my.cnf:/etc/mysql/mysql.conf.d/mysqld.cnf" -v "$cur_path/run/:/var/run/mysql" -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" -d mysql:5.7

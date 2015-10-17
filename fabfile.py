from fabric import colors
from fabric import api as fab
from fabric import decorators
from fabric.contrib import files

import os, getpass

fab.env.colors = True

OS_COMMANDS = ('sudo apt-get install aptitude',
               'sudo aptitude update',
               'sudo aptitude install python-dev',
               'sudo aptitude install python-pip',
               'sudo aptitude install python-virtualenv supervisor uwsgi uwsgi-plugin-python nginx',
               )

certCommands = (
'openssl genrsa -aes256 -out {installDir}/server/server.key 4096',
'openssl req -new -key {installDir}/server/server.key -out {installDir}/server/server.csr',
'cp {installDir}/server/server.key {installDir}/server/server.key.org',
'openssl rsa -in {installDir}/server/server.key.org -out {installDir}/server/server.key',
'openssl x509 -req -days 365 -in {installDir}/server/server.csr -signkey {installDir}/server/server.key -out {installDir}/server/server.crt',
)

supervisorTextTemplate = '''
[program:{programName}]
command=uwsgi --ini {uwsgiConfLocation}
autostart=true
autorestart=true
stdout_logfile=/var/log/{programName}.out.log
redirect_stderr=true
user={user}
stopsignal=QUIT
environment=LANG=en_US.UTF-8, LC_ALL=en_US.UTF-8, LC_LANG=en_US.UTF-8
'''

uwsgiTextTemplate = '''
[uwsgi]
socket = /tmp/{programName}.sock
chdir = {installDir}
virtualenv = {venv_location}
home = {venv_location}
uid = {user}
gid = {user}
processes = 4
threads = 2
stats = 127.0.0.1:9191
plugins = python
module = waiter
callable = app
chmod-socket = 666
'''

nginxTextTemplate = '''
# configuration of the server
server {{
    # the port your site will be served on
    listen      {port};
    # the domain name it will serve for
    server_name {serverName}; # substitute your machine's IP address or FQDN

    access_log  /var/log/nginx/access.log;
    error_log  /var/log/nginx/error.log;

	ssl on;
	ssl_certificate {installDir}/server/server.crt;
	ssl_certificate_key {installDir}/server/server.key;

	ssl_session_timeout 5m;

    ssl_protocols        TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers          HIGH:!aNULL:!MD5;
	ssl_prefer_server_ciphers on;

    location /assets {{
        alias {installDir}/static/assets;
        expires 1d;
    }}

    location /waiter {{
      include {installDir}/server/uwsgi_params;
      uwsgi_pass unix:/tmp/{programName}.sock;
    }}

    location /download {{
        internal;
        alias {basePath};
    }}

}}
'''

def create_venv(venv_home, venv_name):
    venv_location = os.path.join(venv_home, venv_name)
    fab.local('virtualenv -p python2.7 %s' % venv_location)
    return venv_location

def get_venv_prefix(venv_location):
    return '/bin/bash %s' % os.path.join(venv_location, 'bin', 'activate')

def install_venv_requirements(installDir, venv_location, prefix):
    fab.local('%s && %s install -r %s' % (prefix,
                                          os.path.join(venv_location, 'bin', 'pip'),
                                          os.path.join(installDir, 'requirements.txt')))

def deactivate_venv():
    fab.local('deactivate')

def run_command_list(commands, values=None):
    for command in commands:
        if values:
            fab.local(command.format(**values))
        else:
            fab.local(command)

def write_sudo_file(filename, text):
    files.append(filename, text, use_sudo=True)

@fab.task
@decorators.hosts(['localhost'])
def install():
    user = getpass.getuser()
    installDir = os.getcwd()

    run_command_list(OS_COMMANDS)

    venv_home = fab.prompt(colors.cyan('Specify directory where you want the '
                                       'virtual environment to be created:'),
                           default='%s/virtualenvs' % os.path.expanduser('~'))
    venv_name = fab.prompt(colors.cyan('Specify the name of the environment'),
                           default='waiter')
    venv_location = create_venv(venv_home, venv_name)
    prefix = get_venv_prefix(venv_location)
    install_venv_requirements(installDir, venv_location, prefix)

    programName = fab.prompt(colors.cyan('Specify program name'), default='waiter')
    basePath = fab.prompt(colors.cyan('Specify base path'), default=os.path.expanduser('~'))
    serverName = fab.prompt(colors.cyan('Specify server IP address or FQDN'), default='127.0.0.1')
    port = fab.prompt(colors.cyan('Specify port to run application on'), default='5000')
    values = {'programName': programName,
              'user': user,
              'venv_location': venv_location,
              'installDir': installDir,
              'uwsgiConfLocation': os.path.join(installDir, 'uwsgi.ini'),
              'port': port,
              'serverName': serverName,
              'basePath': basePath,
              }
    run_command_list(certCommands, values=values)

    uwsgiText = uwsgiTextTemplate.format(**values)
    write_sudo_file(values['uwsgiConfLocation'], uwsgiText)

    supervisorText = supervisorTextTemplate.format(**values)
    write_sudo_file(os.path.join('/etc/supervisor/conf.d', '%s.conf' % values['programName']), supervisorText)

    nginxText = nginxTextTemplate.format(**values)
    write_sudo_file(os.path.join('/etc/nginx/sites-enabled/%s.conf' % values['programName']), nginxText)

    fab.local('sudo supervisorctl update')
    fab.local('sudo supervisorctl restart %s' % values['programName'])
    fab.local('sudo service nginx restart')

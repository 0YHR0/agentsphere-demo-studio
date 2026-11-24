"""Additional demonstrations using the pinned official SDK and Huawei patch."""
import hashlib
import json
import re
import shlex
import time
import uuid
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .core.instrumentation import recorded


class SDKFeatures:
    @recorded
    def create_obs_sandbox(self,template_ref,bucket,bucket_path,mount_dir,read_only=False):
        # Storage uses the Build runtime agency, never AK/SK in metadata.
        metadata={'agentsandbox.storage.obs':json.dumps({'obsMounts':[{
            'bucket':bucket,'bucketPath':bucket_path,'mountDir':mount_dir,
            'readOnly':read_only}]},separators=(',',':'))}
        sandbox=self.Sandbox.create(template=template_ref,metadata=metadata,
            timeout=self.c['sandbox_timeout'],**self.sandbox_options)
        self._sandboxes[sandbox.sandbox_id]=sandbox
        return sandbox.sandbox_id

    @recorded
    def obs_mount_info(self,sid,mount_dir):
        # A writable ordinary directory is not evidence of an OBS mount.
        code="import json; p="+repr(mount_dir)+"; rows=[r.strip().split(' - ',1) for r in open('/proc/self/mountinfo')]; print(json.dumps([{'mount_dir':a.split()[4],'filesystem':b.split()[0],'options':a.split()[5],'source':b.split()[1]} for a,b in rows if a.split()[4]==p]))"
        r=self.command(sid,'python3 -c '+shlex.quote(code),user='root')
        mounts=json.loads(r['stdout'])
        if len(mounts)!=1 or not any(n in mounts[0]['filesystem'].lower() for n in ('fuse','obs','s3')):
            raise RuntimeError('未发现OBS/FUSE挂载，拒绝把普通目录读写记为通过')
        return dict(sandbox_id=sid,mount=mounts[0])

    @recorded
    def obs_readonly_check(self,sid,mount_dir,expected):
        sandbox=self.connect(sid)
        content=sandbox.files.read(mount_dir+'/evidence.txt',user='root',request_timeout=30)
        if content!=expected:raise RuntimeError('只读挂载内容不一致')
        code="import json,errno; p="+repr(mount_dir+'/readonly-denied.txt')+"\ntry:\n open(p,'x').write('must not succeed')\n print(json.dumps({'denied':False}))\nexcept OSError as e:\n print(json.dumps({'denied':e.errno in (errno.EROFS,errno.EACCES,errno.EPERM),'errno':e.errno}))"
        r=self.command(sid,'python3 -c '+shlex.quote(code),user='root')
        result=json.loads(r['stdout'])
        if not result['denied']:raise RuntimeError('readOnly未拒绝写入')
        if sandbox.files.exists(mount_dir+'/readonly-denied.txt',user='root',request_timeout=15):
            raise RuntimeError('只读挂载出现了写入文件')
        return dict(sandbox_id=sid,read_matches=True,**result)

    @recorded
    def build_template_async(self,on_created,options=None):
        template=self.Template().from_image(self.c['image']).set_user('root')
        template=template.set_start_cmd(self.c['start_cmd'] or 'sleep infinity',self.c['ready_cmd'] or 'true')
        name='agentsphere-sdk-'+uuid.uuid4().hex[:10]
        def on_log(entry):
            match=re.search(r'Template created with ID: ([^,]+), Build ID: (\S+)',entry.message)
            if match:on_created(dict(template_id=match[1],build_id=match[2],name=name,status='waiting',owned=True))
        build=self.Template.build_in_background(template,name=name,arch=self.c['arch'],
            gateway_id=self.c['gateway_id'],cpu_count=self.c['cpu'],memory_mb=self.c['memory_mb'],
            on_build_logs=on_log,**(options or {}),**self.options)
        return dict(template_id=build.template_id,build_id=build.build_id,name=name,status='building',owned=True)

    @recorded
    def delete_build(self,resource):
        self.Template.delete_build(resource['template_id'],resource['build_id'],**self.options)
        detail=self.query('/templates/'+resource['template_id']+'/builds/'+resource['build_id'],allow_missing=True)
        if detail is not None:raise RuntimeError('删除快照后仍能查询到该Build')
        return dict(template_id=resource['template_id'],build_id=resource['build_id'],detail_http=404)

    @recorded
    def sdk_info(self,sid):
        sandbox=self.connect(sid);info=sandbox.get_info(request_timeout=30)
        if info.sandbox_id!=sid:raise RuntimeError('get_info返回了不同实例')
        running=sandbox.is_running(request_timeout=15)
        if not running:raise RuntimeError('is_running返回False')
        return dict(sandbox_id=info.sandbox_id,template_id=info.template_id,is_running=running,
            started_at=str(info.started_at),end_at=str(info.end_at),metadata=info.metadata)

    @recorded
    def sdk_metrics(self,sid):
        response=self.connect(sid)._envd_api.get('/metrics');response.raise_for_status()
        data=response.json()
        required=('cpu_count','cpu_used_pct','mem_total','mem_used','mem_cache','disk_total','disk_used')
        if not isinstance(data,dict) or any(k not in data for k in required):raise RuntimeError('metrics字段不完整')
        return dict(sandbox_id=sid,metrics=data,note='envd当前实例指标；内存缓存与进程RSS不是同一口径')

    @recorded
    def sdk_timeout(self,sid,seconds):
        sandbox=self.connect(sid);before=self.sandbox_detail(sid)
        started=datetime.now(timezone.utc);sandbox.set_timeout(seconds,request_timeout=30)
        # Do not connect again here: connect would reset the requested TTL.
        after=self.sandbox_detail(sid)
        end=datetime.fromisoformat(after['endAt'].replace('Z','+00:00'))
        remaining=(end-started).total_seconds()
        if abs(remaining-seconds)>15:raise RuntimeError('到期时间未按set_timeout更新')
        return dict(sandbox_id=sid,timeout_seconds=seconds,end_at_before=before.get('endAt'),end_at_after=after['endAt'],observed_remaining_seconds=remaining)

    @recorded
    def sdk_envs(self,sid):
        sandbox=self.connect(sid)
        result=sandbox.commands.run('printf "%s" "$STUDIO_SANDBOX_ENV"',user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=10)
        if result.stdout!='created-by-studio':raise RuntimeError('创建时envs未生效')
        return dict(sandbox_id=sid,env_name='STUDIO_SANDBOX_ENV',stdout=result.stdout,exit_code=result.exit_code)

    @recorded
    def file_directory(self,sid,directory):
        fs=self.connect(sid).files;opts={'user':self.c['command_user'],'request_timeout':30}
        nested=directory+'/nested/deep';fs.make_dir(nested,**opts)
        fs.write(nested+'/info.txt','AgentSphere file metadata',**opts)
        names=[row.name for row in fs.list(nested,**opts)];info=fs.get_info(nested+'/info.txt',**opts)
        exists=fs.exists(nested+'/info.txt',**opts);missing=fs.exists(nested+'/missing-'+uuid.uuid4().hex,**opts)
        if not exists or missing or 'info.txt' not in names or info.size!=len('AgentSphere file metadata'):
            raise RuntimeError('目录、存在性或属性验证失败')
        return dict(sandbox_id=sid,directory=nested,entries=names,exists=exists,missing_exists=missing,size=info.size,type=str(info.type))

    @recorded
    def file_manage(self,sid,directory):
        fs=self.connect(sid).files;opts={'user':self.c['command_user'],'request_timeout':30}
        source=directory+'/rename-source';target=directory+'/rename-target'
        fs.make_dir(source+'/deep',**opts);fs.write(source+'/deep/a.txt','rename and delete',**opts)
        fs.rename(source,target,**opts);fs.rename(target+'/deep/a.txt',target+'/deep/b.txt',**opts)
        if fs.exists(source,**opts) or fs.exists(target+'/deep/a.txt',**opts) or fs.read(target+'/deep/b.txt',**opts)!='rename and delete':
            raise RuntimeError('文件或目录重命名失败')
        fs.remove(target+'/deep/b.txt',**opts)
        if fs.exists(target+'/deep/b.txt',**opts):raise RuntimeError('文件删除失败')
        fs.write(target+'/deep/c.txt','owned disposable file',**opts);fs.remove(target,**opts)
        if fs.exists(target,**opts):raise RuntimeError('目录递归删除失败')
        return dict(sandbox_id=sid,file_renamed=True,directory_renamed=True,file_removed=True,directory_removed=True,scope=directory)

    @recorded
    def file_batch_stream(self,sid,directory):
        from e2b.sandbox.filesystem.filesystem import WriteEntry
        fs=self.connect(sid).files;opts={'user':self.c['command_user'],'request_timeout':30}
        fs.make_dir(directory,**opts);payload=bytes(range(256))*1024
        fs.write_files([WriteEntry(path=directory+'/a.txt',data='batch A'),WriteEntry(path=directory+'/b.bin',data=payload)],**opts)
        downloaded=b''.join(fs.read(directory+'/b.bin',format='stream',**opts))
        if downloaded!=payload or fs.read(directory+'/a.txt',**opts)!='batch A':raise RuntimeError('批量写入或流式下载内容不符')
        return dict(sandbox_id=sid,batch_files=2,bytes=len(downloaded),sha256=hashlib.sha256(downloaded).hexdigest(),stream_verified=True)

    @recorded
    def file_urls(self,sid,directory):
        sandbox=self.connect(sid);user=self.c['command_user'];path=directory+'/url-transfer.bin'
        sandbox.files.make_dir(directory,user=user);payload=b'AgentSphere signed-url test\x00\xff'
        upload=sandbox.upload_url(path,user=user,use_signature_expiration=60)
        response=sandbox._envd_api.post(upload,files={'file':('sample.bin',payload,'application/octet-stream')})
        response.raise_for_status()
        upload_status=response.status_code
        download=sandbox.download_url(path,user=user,use_signature_expiration=60)
        response=sandbox._envd_api.get(download);response.raise_for_status()
        if response.content!=payload:raise RuntimeError('临时URL下载内容不一致')
        return dict(sandbox_id=sid,upload_http=upload_status,download_http=response.status_code,bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),url_origin=urlsplit(download).netloc,signature_expiration_seconds=60,
            note='通过SDK客户端携带网关路由与鉴权；不导出含签名的完整URL')

    @recorded
    def command_stream(self,sid,emit=None):
        sandbox=self.connect(sid);events=[];start=time.perf_counter()
        def callback(channel,data):
            events.append(dict(channel=channel,text=data,offset_s=round(time.perf_counter()-start,4)))
            if emit:emit(channel+': '+data.rstrip())
        result=sandbox.commands.run('printf "first:%s\\n" "$STUDIO_COMMAND_ENV"; sleep 0.2; echo second; echo warning >&2',
            user=self.c['command_user'],cwd=self.c['command_cwd'],envs={'STUDIO_COMMAND_ENV':'command-only'},timeout=10,
            on_stdout=lambda data:callback('stdout',data),on_stderr=lambda data:callback('stderr',data))
        stdout=''.join(e['text'] for e in events if e['channel']=='stdout');stderr=''.join(e['text'] for e in events if e['channel']=='stderr')
        after=sandbox.commands.run('printf "%s" "${STUDIO_COMMAND_ENV-unset}"',user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=10)
        if stdout!=result.stdout or stderr!=result.stderr or 'first:command-only' not in stdout or 'warning' not in stderr or after.stdout!='unset':
            raise RuntimeError('stdout/stderr回调或命令级envs隔离验证失败')
        return dict(sandbox_id=sid,stdout=stdout,stderr=stderr,exit_code=result.exit_code,events=events,env_after=after.stdout)

    @recorded
    def command_timeout(self,sid,directory):
        from e2b.exceptions import TimeoutException
        from e2b.sandbox.commands.command_handle import CommandExitException
        sandbox=self.connect(sid);sandbox.files.make_dir(directory,user=self.c['command_user'])
        path=directory+'/timeout.pid';started=time.perf_counter();caught=None
        try:
            sandbox.commands.run('echo $$ > '+shlex.quote(path)+'; exec sleep 20',user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=1,request_timeout=10)
        except (TimeoutException,CommandExitException) as exc:caught=exc
        elapsed=time.perf_counter()-started
        if caught is None or not .5<=elapsed<10:raise RuntimeError('未观察到命令执行超时')
        pid=int(sandbox.files.read(path,user=self.c['command_user']))
        absent=sandbox.commands.run('test ! -e /proc/'+str(pid),user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=5)
        if absent.exit_code!=0:raise RuntimeError('请求超时后进程仍存活，不能当作执行超时通过')
        return dict(sandbox_id=sid,timeout_seconds=1,elapsed_s=elapsed,pid=pid,process_terminated=True,exception_type=type(caught).__name__)

    @recorded
    def process_background(self,sid):
        from e2b.sandbox.commands.command_handle import CommandExitException
        sandbox=self.connect(sid);cmd='exec python3 -u -c '+shlex.quote('import time; print("background-ready",flush=True); time.sleep(20)')
        handle=sandbox.commands.run(cmd,background=True,user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=30)
        pid=handle.pid
        try:
            if pid not in [p.pid for p in sandbox.commands.list()]:raise RuntimeError('后台进程未出现在列表')
            handle.disconnect();attached=sandbox.commands.connect(pid,timeout=5)
            if attached.pid!=pid:raise RuntimeError('进程重连PID不一致')
            killed=sandbox.commands.kill(pid)
            if not killed:raise RuntimeError('kill未确认终止本工具进程')
            exit_code=None
            try:attached.wait()
            except CommandExitException as exc:
                exit_code=exc.exit_code
                if exc.exit_code not in (137,143,-9,-15,-1):raise
            if pid in [p.pid for p in sandbox.commands.list()]:raise RuntimeError('终止后进程仍在列表')
            return dict(sandbox_id=sid,pid=pid,listed=True,reconnected=True,killed=killed,absent_after=True,exit_code=exit_code)
        finally:sandbox.commands.kill(pid)

    @recorded
    def pty_session(self,sid):
        from e2b import PtySize
        sandbox=self.connect(sid);terminal=sandbox.pty.create(PtySize(rows=24,cols=80),user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=15)
        pid=terminal.pid;output=[]
        try:
            sandbox.pty.resize(pid,PtySize(rows=40,cols=120));terminal.disconnect()
            attached=sandbox.pty.connect(pid,timeout=10)
            sandbox.pty.send_stdin(pid,b"printf '\\nPTY_OK_%s\\n' $((6*7)); test -t 1; printf 'TTY=%s\\n' $?; stty size; exit\n")
            result=attached.wait(on_pty=lambda data:output.append(data.decode(errors='replace')))
            text=''.join(output)
            if result.exit_code!=0 or 'PTY_OK_42' not in text or 'TTY=0' not in text or '40 120' not in text:
                raise RuntimeError('PTY输入、TTY属性、窗口尺寸或退出码验证失败')
            other=sandbox.pty.create(PtySize(rows=24,cols=80),user=self.c['command_user'],cwd=self.c['command_cwd'],timeout=10)
            other_pid=other.pid
            try:
                killed=sandbox.pty.kill(other_pid)
                if not killed:raise RuntimeError('pty.kill返回False')
            finally:other.disconnect()
            return dict(sandbox_id=sid,pid=pid,reconnected=True,resized_to={'rows':40,'cols':120},stdout=text,exit_code=result.exit_code,killed_pty=other_pid)
        finally:sandbox.pty.kill(pid)

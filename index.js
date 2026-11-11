import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';
const execFileAsync=promisify(execFile);
const packageRoot=path.dirname(fileURLToPath(import.meta.url));
let runtimeConfig={};
function root(){const configured=process.env.DSH_GPU_MONITOR_ROOT;if(configured)return configured;const workspace=path.resolve(packageRoot,'..');return existsSync(path.join(workspace,'ssh','.env'))?workspace:packageRoot}
async function snapshot(){
 const script=path.join(root(),'ssh','connect.py');
 const command='nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,clocks.current.graphics,clocks.current.memory --format=csv,noheader,nounits; echo __DSH_PROCESSES__; nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits; echo __DSH_PS__; ps -eo user=,pid=,etime=,comm= --no-headers; echo __DSH_HOST__; uptime; free -m; df -P / /home 2>/dev/null; echo __DSH_USERS__;';
 try{const args=[script,'-c',command];if(runtimeConfig.host){args.push('--host',runtimeConfig.host,'--port',runtimeConfig.port||'22','--user',runtimeConfig.user||'','--password',runtimeConfig.password||'')};const {stdout}=await execFileAsync(process.env.PYTHON||'python',args,{cwd:root(),timeout:25000,maxBuffer:1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8',PYTHONUTF8:'1'}});
  const lines=stdout.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),mp=lines.indexOf('__DSH_PROCESSES__'),ms=lines.indexOf('__DSH_PS__'),mh=lines.indexOf('__DSH_HOST__'),mu=lines.indexOf('__DSH_USERS__');
  const gl=lines.slice(0,mp<0?lines.length:mp).filter(s=>/^\d+\s*,/.test(s)),pl=lines.slice(mp+1,ms<0?lines.length:ms).filter(Boolean),ps=lines.slice(ms+1,mu<0?lines.length:mu).filter(Boolean),users=lines.slice(mu+1).filter(s=>!s.startsWith('[ssh]'));
  const owners=new Map(ps.map(s=>{const p=s.trim().split(/\s+/);return[p[1],p[0]]}));
  const gpus=gl.map(s=>{const p=s.split(',').map(x=>x.trim());return{index:p[0],uuid:p[1],name:p[2],utilization:+p[3]||0,memoryUsed:+p[4]||0,memoryTotal:+p[5]||0,temperature:+p[6]||0,power:+p[7]||0,powerLimit:+p[8]||0,graphicsClock:+p[9]||0,memoryClock:+p[10]||0}});
  const gpuByUuid=new Map(gpus.map(g=>[g.uuid,g.index]));
  const processes=pl.map(s=>{const p=s.split(',').map(x=>x.trim());const psrow=ps.find(x=>x.split(/\s+/)[1]===p[1]);const parts=psrow?psrow.split(/\s+/):[];return{gpu:gpuByUuid.get(p[0])||p[0]||'未知',pid:p[1],name:p[2],memory:+p[3]||0,owner:owners.get(p[1])||'未知',runtime:parts[2]||'未知'}});
  const hostLines=lines.slice(mh+1,mu<0?lines.length:mu); const load=hostLines.find(x=>x.includes('load average:'))||''; const mem=hostLines.find(x=>/^Mem:/.test(x))||''; const disk=hostLines.filter(x=>/^\/dev\//.test(x)).map(x=>{const p=x.split(/\s+/);return{mount:p[p.length-1],used:p[4]||'',percent:p[3]||''}}); const host={load:load.split('load average:')[1]?.trim()||'未知',memory:mem};
  const conclusion=!gpus.length?'未读取到 GPU 数据':gpus.some(g=>g.utilization>80||g.memoryUsed/g.memoryTotal>.9)?'GPU 负载较高，存在繁忙任务。':gpus.some(g=>g.utilization>20||g.memoryUsed>0)?'GPU 正在使用，当前负载中等。':'GPU 基本空闲，可考虑安排任务。';
  return{ok:true,fetchedAt:new Date().toISOString(),gpus,processes,users,host,disk,conclusion};
 }catch(e){const raw=e?.stderr?.trim()||e?.message||'SSH collection failed';const error=raw.includes('找不到配置文件')||raw.includes('No such file')?'未找到 SSH 配置文件。请复制 ssh/.env.example 为 ssh/.env，并填写服务器信息。':raw.includes('用户名或密码')||raw.includes('Authentication')?'SSH 用户名或密码错误。':'SSH 连接失败：'+raw;return{ok:false,error,fetchedAt:new Date().toISOString()}}
}
export const inject=['webServer'];
function json(res,status,value){res.statusCode=status;res.setHeader('content-type','application/json; charset=utf-8');res.end(JSON.stringify(value))}
export function apply(ctx){const web=ctx.get('webServer');if(!web)return;ctx.effect(()=>web.register({kind:'exact',path:'/api/dsh-gpu-monitor',resource:async()=>new Response(JSON.stringify(await snapshot()),{headers:{'content-type':'application/json; charset=utf-8'}})}));ctx.effect(()=>web.register({kind:'exact',path:'/api/dsh-gpu-monitor/config',handler:async(req,res)=>{if(req.method==='GET')return json(res,200,{ok:true,configured:!!runtimeConfig.host});if(req.method!=='POST')return json(res,405,{ok:false,error:'method not allowed'});let body='';for await(const chunk of req)body+=chunk;try{const v=JSON.parse(body);if(!v.host||!v.user||!v.password)return json(res,400,{ok:false,error:'host, user and password are required'});runtimeConfig={host:String(v.host),port:String(v.port||22),user:String(v.user),password:String(v.password)};return json(res,200,{ok:true})}catch{return json(res,400,{ok:false,error:'invalid JSON'})}}}))}


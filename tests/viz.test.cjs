// Canvas logic smoke test, not a substitute for rendered-browser visual acceptance.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('web/viz.js', 'utf8');

test('front and rear plasma share one geometry sample set and resize invalidates frozen geometry',()=>{
  let frame,clock=0,width=340,samples=0;
  const ctx=new Proxy({}, {get:(_,key)=>key==='createRadialGradient'?()=>({addColorStop(){}}):()=>{},set:()=>true});
  const canvas={width:0,height:0,getContext:()=>ctx,getBoundingClientRect:()=>({width,height:160})};
  const instrumented=source.replace('const orbit=ORBITS[index],radius=',
    'if(arguments.length===3)sampled();const orbit=ORBITS[index],radius=');
  vm.runInNewContext(instrumented.replace('}catch(ex){','}catch(ex){ throw ex;'),{
    window:{devicePixelRatio:1},document:{hidden:false,getElementById:id=>id==='viz'?canvas:id==='motion'?{value:'off'}:null},
    location:{pathname:'/overlay'},performance:{now:()=>clock},requestAnimationFrame:fn=>frame=fn,
    matchMedia:()=>({matches:false}),Math,sampled:()=>samples++});
  frame(clock+=300);assert.equal(samples,432);
  frame(clock+=300);assert.equal(samples,432);
  width=360;frame(clock+=300);assert.equal(samples,864);
});

test('DPI transition updates logical drawing bounds even with unchanged backing pixels',()=>{
  let frame,clock=0,width=340,height=160;const transforms=[],clears=[];
  const ctx=new Proxy({}, {get:(_,key)=>{
    if(key==='setTransform')return (...args)=>transforms.push(args);
    if(key==='clearRect')return (...args)=>clears.push(args);
    if(key==='createRadialGradient')return ()=>({addColorStop(){}});
    return ()=>{};
  },set:()=>true});
  const canvas={width:0,height:0,getContext:()=>ctx,getBoundingClientRect:()=>({width,height})};
  const window={devicePixelRatio:1};
  const document={hidden:false,getElementById:id=>id==='viz'?canvas:id==='motion'?{value:'on'}:null};
  vm.runInNewContext(source.replace('}catch(ex){','}catch(ex){ throw ex;'),{
    window,document,location:{pathname:'/overlay'},performance:{now:()=>clock},
    requestAnimationFrame:fn=>frame=fn,matchMedia:()=>({matches:false}),Math});
  frame(clock+=34);
  assert.deepEqual(clears.at(-1),[0,0,340,160]);
  width=170;height=80;window.devicePixelRatio=2;frame(clock+=34);
  assert.equal(canvas.width,340);assert.equal(canvas.height,160);
  assert.deepEqual(transforms.at(-1),[2,0,0,2,0,0]);
  assert.deepEqual(clears.at(-1),[0,0,170,80]);
  width=340;height=160;window.devicePixelRatio=1;frame(clock+=34);
  assert.deepEqual(transforms.at(-1),[1,0,0,1,0,0]);
  assert.deepEqual(clears.at(-1),[0,0,340,160]);
});

test('plasma reuses bounded soft sprites and restores alpha after each draw',()=>{
  let frame,clock=0,created=0,draws=0;
  const state={globalAlpha:1},stack=[];
  const ctx=new Proxy(state,{get:(target,key)=>{
    if(key in target)return target[key];
    if(key==='save')return ()=>stack.push(target.globalAlpha);
    if(key==='restore')return ()=>{target.globalAlpha=stack.pop();};
    if(key==='createRadialGradient')return ()=>({addColorStop(){}});
    if(key==='drawImage')return (_image,...rect)=>{
      assert.ok(rect.every(Number.isFinite));
      assert.ok(target.globalAlpha>=0&&target.globalAlpha<=1);draws++;
    };
    return ()=>{};
  }});
  const elements={motion:{value:'on'},viz:{getContext:()=>ctx,getBoundingClientRect:()=>({width:340,height:308})}};
  const document={hidden:false,getElementById:id=>elements[id],createElement:()=>{
    created++;return {getContext:()=>ctx};
  }};
  vm.runInNewContext(source.replace('}catch(ex){','}catch(ex){ throw ex;'),{window:{devicePixelRatio:1},document,location:{pathname:'/overlay'},
    performance:{now:()=>clock},requestAnimationFrame:fn=>frame=fn,matchMedia:()=>({matches:false}),Math});
  frame(clock+=34);const first=created;
  for(let i=0;i<60;i++)frame(clock+=34);
  assert.ok(draws>10000);assert.ok(first>0&&first<=8);
  assert.equal(created,first);assert.equal(ctx.globalAlpha,1);
});

for(const [pathname,width,height] of [['/',640,310],['/orb',230,195],['/overlay',340,160]]) test(`orb ${pathname} stays finite, respects reduced motion and never invents counts`, () => {
  let frame, clock=0, arcs=0;
  const gradient = {addColorStop(offset) {assert.ok(offset>=0 && offset<=1);}};
  const ctx = new Proxy({}, {get(_target, key) {
    if (key==='createRadialGradient') return (...args) => {assert.ok(args.every(Number.isFinite));assert.ok(args[2]>=0&&args[5]>=0);return gradient;};
    if (key==='arc') return (x,y,r) => {assert.ok([x,y,r].every(Number.isFinite));assert.ok(r>=0);arcs++;};
    return () => {};
  },set(){return true;}});
  const elements = Object.fromEntries(['dbg','coreNum','coreBlk','evtCount','blkCount','motion'].map(id=>[id,{textContent:'17',value:'on',classList:{toggle(){}}}]));
  elements.viz = {getContext:()=>ctx,getBoundingClientRect:()=>({width,height}),width:0,height:0};
  const window = {devicePixelRatio:1};
  const document = {hidden:false,getElementById:id=>elements[id]};
  vm.runInNewContext(source,{location:{pathname},window,document,performance:{now:()=>clock},requestAnimationFrame:fn=>frame=fn,matchMedia:()=>({matches:false}),Math});
  for(let i=0;i<15;i++)frame(clock+=34);
  window.guardianVizPush({demo:true,color:'#ff5470',kind:'bad'});
  for(let i=0;i<100;i++)frame(clock+=34);
  assert.ok(arcs>0);
  assert.equal(elements.evtCount.textContent,'17');
  assert.equal(elements.blkCount.textContent,'17');
  assert.ok(!elements.dbg.textContent.startsWith('报错'));
  document.body={classList:{contains:()=>true}};frame(clock+=34);
  elements.motion.value='off';frame(clock+=300);
  document.hidden=true;const before=arcs;frame(clock+=300);assert.equal(arcs,before);
});

test('action-only panel does not start hidden canvas animation',()=>{
  let started=false;
  vm.runInNewContext(source,{location:{pathname:'/monitor'},requestAnimationFrame(){started=true;}});
  assert.equal(started,false);
});


test('source nodes orbit within the viewport, freeze for reduced motion and emit from their current position',()=>{
  let frame,clock=0;const positions=[],emissions=[];
  const ctx=new Proxy({}, {get:(_,key)=>key==='createRadialGradient'?()=>({addColorStop(){}}):()=>{},set:()=>true});
  const elements={motion:{value:'on'},viz:{width:0,height:0,getContext:()=>ctx,getBoundingClientRect:()=>({width:340,height:308})}};
  const instrumented=source.replace('function drawSource(s, T){','function drawSource(s, T){ capture({...s});')
    .replace('particles.push({','emitted({...p0}); particles.push({');
  const window={devicePixelRatio:1};
  vm.runInNewContext(instrumented,{window,location:{pathname:'/overlay'},document:{hidden:false,getElementById:id=>elements[id]},
    performance:{now:()=>clock},requestAnimationFrame:fn=>frame=fn,matchMedia:()=>({matches:false}),Math,
    capture:s=>positions.push(s),emitted:p=>emissions.push(p)});
  frame(clock=34);const initial=positions.splice(0);
  for(let i=0;i<240;i++)frame(clock+=100);
  for(const p of positions){assert.ok(p.x>12&&p.x<328);assert.ok(p.y>12&&p.y<296);}
  const latest=positions.slice(-5);
  for(const p of initial){const q=latest.find(s=>s.index===p.index);assert.ok(Math.hypot(p.x-q.x,p.y-q.y)>1);}
  window.guardianVizPush({sourceIndex:1,kind:'ok'});positions.length=0;frame(clock+=34);
  const sourceNow=positions.find(s=>s.index===1);
  assert.equal(emissions.length,12);
  assert.equal(emissions[0].x,sourceNow.x);assert.equal(emissions[0].y,sourceNow.y);
  elements.motion.value='off';positions.length=0;frame(clock+=300);const frozen=positions.splice(0);
  frame(clock+=300);
  for(const p of frozen){const q=positions.find(s=>s.index===p.index);assert.equal(p.x,q.x);assert.equal(p.y,q.y);}
});


test('dynamic sources emit by identity and unknown sources never borrow a node',()=>{
 let frame,clock=0;const emissions=[],positions=[];
 const ctx=new Proxy({}, {get:(_,key)=>key==='createRadialGradient'?()=>({addColorStop(){}}):()=>{},set:()=>true});
 const elements={motion:{value:'on'},viz:{width:0,height:0,getContext:()=>ctx,getBoundingClientRect:()=>({width:340,height:308})}};
 const instrumented=source.replace('particles.push({','emitted(s.id,col.c); particles.push({')
   .replace('function drawSource(s, T){','function drawSource(s, T){ capture({...s});')
   .replace('}catch(ex){','}catch(ex){ throw ex;');
 const window={devicePixelRatio:1};
 vm.runInNewContext(instrumented,{window,location:{pathname:'/overlay'},document:{hidden:false,getElementById:id=>elements[id]},
  performance:{now:()=>clock},requestAnimationFrame:fn=>frame=fn,matchMedia:()=>({matches:false}),Math,
  emitted:(id,color)=>emissions.push({id,color}),capture:p=>positions.push(p)});
 const rows=Array.from({length:7},(_,i)=>({id:i===6?'qoder-hook':'fixture-'+i,name:'Client '+i}));
 window.guardianVizSources(rows);frame(clock+=34);
 window.guardianVizPush({sourceId:'qoder-hook',kind:'ok'});frame(clock+=34);
 assert.equal(emissions.length,12);assert.ok(emissions.every(e=>e.id==='qoder-hook'&&e.color==='#ff8b62'));
 assert.ok(positions.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>0&&p.x<340&&p.y>0&&p.y<308));
 window.guardianVizPush({sourceId:'unknown',sourceIndex:0,kind:'ok'});frame(clock+=34);assert.equal(emissions.length,12);
 window.guardianVizSources(rows.slice().reverse());frame(clock+=34);
 window.guardianVizPush({sourceId:'qoder-hook',kind:'ok'});frame(clock+=34);
 assert.equal(emissions.length,24);assert.ok(emissions.every(e=>e.id==='qoder-hook'));
});

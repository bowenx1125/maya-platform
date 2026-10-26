import fs from "fs";
const D="/workspace/maya-chatform/pw/dumps/", A="/workspace/maya-ui/proposals/chatform/audit/";
const isData=s=>/[^\x00-\x7F]/.test(s)||/^\d+\/\d+\/\d{4}$/.test(s)||/^V\d/.test(s)||/@/.test(s)||s==="Why?";
const keys=d=>{const k=new Set();d.texts.forEach(t=>k.add("text:"+t));(d.hiddenTexts||[]).forEach(t=>k.add("text:"+t));d.attrs.forEach(a=>{for(const f of["aria","title","alt","ph","testid"])if(a[f])k.add(f+":"+a[f])});return k};
let total=0;const rep={};
for(const v of["v2a","v2b"])for(const st of["empty","newconv"])for(const w of[1440,390]){
 const cur=JSON.parse(fs.readFileSync(D+st+"-"+w+".json"));
 const MJ=JSON.parse(fs.readFileSync(A+`final-${v}-${st}-${w}.json`));
 const mk=keys(MJ);
 const need=[...keys(cur)].filter(k=>!isData(k.replace(/^\w+:/,"")));
 const miss=need.filter(k=>!mk.has(k));
 rep[`${v}/${st}-${w}`]=miss;total+=miss.length;}
// Also confirm approved states still 0 (from prior final audit files)
for(const st of["list","create","error"])for(const w of[1440,390]){
 const cur=JSON.parse(fs.readFileSync(D+st+"-"+w+".json"));
 const MJ=JSON.parse(fs.readFileSync(A+`final-${st}-${w}.json`));
 const mk=keys(MJ);
 let need=[...keys(cur)].filter(k=>!isData(k.replace(/^\w+:/,"")));
 if(st==="create"&&w===1440) need=need.filter(k=>k!=="text:New");
 const miss=need.filter(k=>!mk.has(k));
 rep[`approved/${st}-${w}`]=miss;total+=miss.length;}
fs.writeFileSync(A+"FINAL-v2-RESULT.txt",JSON.stringify(rep,null,2)+"\nTOTAL MISSING "+total+"\n");
console.log(JSON.stringify(rep,null,0).replace(/\],/g,"],\n"));
console.log("TOTAL MISSING",total);

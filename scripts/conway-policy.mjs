// Evaluate/log with the installed official Conway engine, never execute a tool.
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const source=process.argv[2];
const {PolicyEngine}=await import(pathToFileURL(path.join(source,'dist/agent/policy-engine.js')));
const {createDatabase}=await import(pathToFileURL(path.join(source,'dist/state/database.js')));
const db=createDatabase(path.resolve('policy.sqlite3'));
let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>8192)throw Error('Input limit');}
const proposal=JSON.parse(input);
const rule={id:'zar-zero-authority',priority:0,description:'No execution authority',appliesTo:{by:'all'},evaluate:r=>({
 rule:'zar-zero-authority',action:r.tool.name==='read_file'?'quarantine':'deny',
 reasonCode:'HUMAN_REVIEW_REQUIRED',humanMessage:'Proposal only; no tool execution'})};
const engine=new PolicyEngine(db.raw,[rule]);
const decision=engine.evaluate({tool:{name:proposal.tool,riskLevel:'safe',category:'vm'},args:proposal.args,
 context:{},turnContext:{inputSource:'external',turnToolCallCount:0}});
engine.logDecision(decision);
console.log(JSON.stringify({action:decision.action,reasonCode:decision.reasonCode,toolName:decision.toolName,argsHash:decision.argsHash}));
db.close();

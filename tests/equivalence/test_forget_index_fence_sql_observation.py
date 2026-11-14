"""Real builtin SQLite observation tests, with no original release imports."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


HELPER = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-source-clock.mjs"


def _run(body):
    node = os.environ.get("MEMORY_EQ_NODE") or shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only SQL control")
    script = f"""
import assert from 'node:assert/strict';
import {{DatabaseSync}} from 'node:sqlite';
import {{deserialize}} from 'node:v8';
import {{installOriginalSqlObservation}} from {json.dumps(HELPER.as_uri())};
const rows=[],failures=[],refs=new WeakMap();let nextRef=0;
const ref=value=>{{if(!refs.has(value))refs.set(value,++nextRef);return refs.get(value);}};
const decode=value=>deserialize(Buffer.from(value.v8Hex,'hex'));
const db=new DatabaseSync(':memory:');
const observer=installOriginalSqlObservation({{DatabaseSync,qualifyStack:()=>({{kind:'labelled-builtin-only-source'}}),
 event:(name,row)=>rows.push({{eventName:name,...row}}),ref,onControlFailure:error=>failures.push(error)}});
try{{
{body}
assert.deepEqual(failures,[]);
}}finally{{observer.restore();db.close();}}
process.stdout.write(JSON.stringify({{kind:'builtin-only-sql-observation',originalReleaseModulesImported:false}})+'\\n');
"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", script], env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "kind": "builtin-only-sql-observation", "originalReleaseModulesImported": False,
    }


def test_all_actual_statements_transactions_arguments_returns_and_typed_errors_are_retained():
    _run("""
db.exec('CREATE TABLE facts (id INTEGER PRIMARY KEY, value TEXT UNIQUE); BEGIN IMMEDIATE');
const insert=db.prepare('INSERT INTO facts VALUES (?,?)');
const inserted=insert.run(7,'actual local bytes');
const insertReturn=rows.find(row=>row.eventName==='original-selected-sql-return'&&row.operation==='run');
assert.equal(insertReturn.resultRef,ref(inserted));assert.deepEqual(decode(insertReturn.result),inserted);
const request=rows.find(row=>row.eventName==='original-selected-sql-call'&&row.operation==='run');
assert.deepEqual(decode(request.arguments),[7,'actual local bytes']);assert.equal(request.transactionActive,true);
db.exec('COMMIT');
const query=db.prepare('SELECT id,value FROM facts');query.setReadBigInts(true);
const one=query.get(),all=query.all();assert.equal(typeof one.id,'bigint');assert.equal(all.length,1);
assert.equal(rows.findLast(row=>row.operation==='get'&&row.eventName.endsWith('return')).resultRef,ref(one));
assert.equal(rows.findLast(row=>row.operation==='all'&&row.eventName.endsWith('return')).resultRef,ref(all));
const terminal=rows.find(row=>row.operation==='exec'&&row.sql==='COMMIT'&&row.eventName.endsWith('return'));
assert.equal(terminal.transactionActive,false);assert.equal(decode(terminal.result),undefined);
let actualError;try{insert.run(7,'duplicate');}catch(error){actualError=error;}
assert(actualError instanceof Error);
const failure=rows.findLast(row=>row.eventName==='original-selected-sql-throw');assert.equal(failure.errorRef,ref(actualError));
assert.equal(failure.message,actualError.message);assert.equal(decode(failure.privateError).message,actualError.message);
for(const property of failure.ownProperties.filter(row=>row.value))assert.deepEqual(decode(property.value),actualError[property.key]);
for(const entered of rows.filter(row=>row.eventName==='original-selected-sql-call')){
 const settlements=rows.filter(row=>row.callId===entered.callId&&['original-selected-sql-return','original-selected-sql-throw'].includes(row.eventName));
 assert.equal(settlements.length,1);assert.equal(settlements[0].originalMethodRef,entered.originalMethodRef);
}
""")


def test_iterate_is_not_eagerly_consumed_and_actual_iterator_next_results_are_retained():
    _run("""
db.exec('CREATE TABLE facts(id); INSERT INTO facts VALUES(1),(2),(3)');
const statement=db.prepare('SELECT id FROM facts ORDER BY id'),iterator=statement.iterate();
const opened=rows.findLast(row=>row.operation==='iterate'&&row.eventName.endsWith('return'));
assert.equal(opened.resultRef,ref(iterator));assert.equal(rows.some(row=>row.operation==='iterate.next'),false);
assert.equal(iterator[Symbol.iterator](),iterator);
const first=iterator.next();assert.equal(first.value.id,1);assert.equal(first.done,false);
const consumed=rows.findLast(row=>row.operation==='iterate.next'&&row.eventName.endsWith('return'));
assert.equal(consumed.resultRef,ref(first));assert.equal(consumed.resultPrototypeIsNull,Object.getPrototypeOf(first)===null);
assert.equal(JSON.stringify(decode(consumed.result)),JSON.stringify(first));
const rest=[...iterator];assert.deepEqual(rest.map(row=>row.id),[2,3]);
assert.equal(rows.filter(row=>row.operation==='iterate.next'&&row.eventName.endsWith('return')).length,4);
""")


def test_unqualified_observer_queries_are_not_misattributed_to_original_sql():
    _run("""
observer.restore();rows.length=0;
const local=installOriginalSqlObservation({DatabaseSync,qualifyStack:()=>null,event:(name,row)=>rows.push({eventName:name,...row}),ref,
 onControlFailure:error=>failures.push(error)});
try{db.exec('CREATE TABLE facts(id)');assert.equal(db.prepare('SELECT 42 AS value').get().value,42);assert.equal(rows.length,0);}
finally{local.restore();}
""")

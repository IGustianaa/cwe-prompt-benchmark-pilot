"""Metadata-only inspection; never sends benchmark samples to a model."""
from pathlib import Path
from collections import Counter,defaultdict
import json,hashlib
import sys
p=Path(sys.argv[0]).resolve().parent/'data'/'vuldetectbench_task1_code.jsonl'
rows=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
cwe=defaultdict(Counter)
for row in rows:cwe[str(row['cwe'])][str(row['answer'])]+=1
out={'source':'https://github.com/Sweetaroo/VulDetectBench/tree/main/dataset/test','file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(rows),'keys':sorted(rows[0]),'label_counts':dict(Counter(row['answer'] for row in rows)),'distinct_cwe_values':len(cwe),'cwe_both_labels':{k:dict(v) for k,v in cwe.items() if v['YES'] and v['NO']},'cwe_zero':dict(cwe.get('0',{})),'unique_code_sha256':len({hashlib.sha256(row['code'].encode()).hexdigest() for row in rows}),'unique_idx':len({row['idx'] for row in rows}),'counts_per_cwe':{k:dict(v) for k,v in sorted(cwe.items())}}
q=Path(sys.argv[1] if len(sys.argv)>1 else Path(sys.argv[0]).resolve().parent/'dataset_audit.json');q.write_text(json.dumps(out,indent=2,ensure_ascii=False));print('saved',q,'rows',out['rows'],'both_labels',out['cwe_both_labels'])

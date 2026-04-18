#!/bin/bash

PERSONAS_DIR=~/.akashik/data/benchmarks/acmb/personas
QUERIES_DIR=~/.akashik/data/benchmarks/acmb/queries
shopt -s nullglob

echo "=== ACMB Pre-flight Check ==="
echo ""

persona_files=("$PERSONAS_DIR"/persona_*.json)

echo "--- File existence ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  q="$QUERIES_DIR/queries_$stem.json"
  echo "  ✓ $base"
  if [ -f "$q" ]; then
    echo "  ✓ queries_$stem.json"
  else
    echo "  - queries_$stem.json not generated yet"
  fi
done
echo ""

echo "--- Persona structure ---"
for p in "${persona_files[@]}"; do
  python3 -c "
import json
path = '$p'
data = json.load(open(path))
label = data['persona_id']
persona_num = int(label.split('_')[-1])
sessions = data.get('sessions', [])
if 5 <= len(sessions) <= 7:
    print(f'  ✓ {label}: {len(sessions)} sessions')
else:
    print(f'  ✗ {label}: expected 5-7 sessions, found {len(sessions)}')
types = {session.get('session_type') for session in sessions}
for required in ['noise', 'drift', 'contradiction']:
    if required in types:
        print(f'  ✓ {label}: has {required} session')
    else:
        print(f'  ✗ {label}: missing {required} session')
for session in sessions:
    turns = session.get('turns', [])
    if 6 <= len(turns) <= 10:
        print(f'  ✓ {label} {session[\"session_id\"]}: {len(turns)} turns')
    else:
        print(f'  ✗ {label} {session[\"session_id\"]}: expected 6-10 turns, found {len(turns)}')
    if session.get('session_type') == 'noise':
        factful = [turn['turn_id'] for turn in turns if turn.get('ground_truth_facts')]
        if factful:
            print(f'  ✗ {label} {session[\"session_id\"]}: noise session has ground_truth_facts on {factful}')
        else:
            print(f'  ✓ {label} {session[\"session_id\"]}: noise session has zero ground_truth_facts')
facts = data.get('facts', [])
commitments = data.get('commitments', [])
if persona_num >= 6:
    current_by_attr = {}
    for fact in facts:
        current_by_attr.setdefault(fact['attribute'], []).append(fact)
    has_chain = any(len(items) >= 3 for items in current_by_attr.values())
    if has_chain:
        print(f'  ✓ {label}: has fact chain length >= 3')
    else:
        print(f'  ✗ {label}: no fact chain length >= 3 found')
    if commitments:
        early = commitments[0].get('opened_session', 99)
        if early <= 2:
            print(f'  ✓ {label}: commitment opens in session {early}')
        else:
            print(f'  ✗ {label}: commitment opens too late (session {early})')
    else:
        print(f'  ✗ {label}: missing commitment')
else:
    print(f'  - {label}: legacy persona, skipping v0.3 chain/early-commitment checks')
"
done
echo ""

echo "--- turn_before validity ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  q="$QUERIES_DIR/queries_$stem.json"
  [ ! -f "$q" ] && continue
  while IFS= read -r turn_before; do
    count=$(grep -c "\"turn_id\": \"$turn_before\"" "$p" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
      echo "  ✓ persona_$stem: $turn_before exists"
    else
      echo "  ✗ persona_$stem: $turn_before NOT FOUND in persona"
    fi
  done < <(python3 -c "
import json
data = json.load(open('$q'))
for q in data['queries']:
    print(q['turn_before'])
")
done
echo ""

echo "--- Commitment fact placement ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  python3 -c "
import json
data = json.load(open('$p'))
for session in data['sessions']:
    for turn in session['turns']:
        facts = turn.get('ground_truth_facts', [])
        commitments = [f for f in facts if f.startswith('c')]
        if commitments and turn['actor'] == 'assistant':
            print(f'  ✗ persona_$stem: {commitments} on ASSISTANT turn {turn[\"turn_id\"]} — will not be retrieved')
        elif commitments and turn['actor'] == 'user':
            print(f'  ✓ persona_$stem: {commitments} on user turn {turn[\"turn_id\"]}')
"
done
echo ""

echo "--- Belief revision: must_exclude vs superseded ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  q="$QUERIES_DIR/queries_$stem.json"
  [ ! -f "$q" ] && continue
  python3 -c "
import json
persona = json.load(open('$p'))
queries = json.load(open('$q'))
superseded = {f['fact_id'] for f in persona['facts'] if f.get('superseded_session')}
for q in queries['queries']:
    if q['query_type'] == 'current_state':
        excl = set(q.get('must_exclude', []))
        overlap = excl & superseded
        if overlap:
            print(f'  ✓ persona_$stem {q[\"query_id\"]}: must_exclude {overlap} are superseded facts')
        else:
            print(f'  ✗ persona_$stem {q[\"query_id\"]}: must_exclude {excl} does not match superseded {superseded}')
"
done
echo ""

echo "--- Paraphrase wording check ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  q="$QUERIES_DIR/queries_$stem.json"
  [ ! -f "$q" ] && continue
  python3 -c "
import json
persona = json.load(open('$p'))
queries = json.load(open('$q'))
fact_nl = {f['fact_id']: f['natural_language'].lower() for f in persona['facts']}
for q in queries['queries']:
    if q['query_type'] == 'paraphrase':
        qt = q['query_text'].lower()
        for fid in q.get('must_include', []):
            nl = fact_nl.get(fid, '')
            if nl and qt == nl:
                print(f'  ✗ persona_$stem {q[\"query_id\"]}: query_text IDENTICAL to natural_language')
            else:
                print(f'  ✓ persona_$stem {q[\"query_id\"]}: query_text differs from natural_language')
"
done
echo ""

echo "--- Noise robustness: target fact introduced early ---"
for p in "${persona_files[@]}"; do
  base=$(basename "$p")
  stem="${base#persona_}"
  stem="${stem%.json}"
  q="$QUERIES_DIR/queries_$stem.json"
  [ ! -f "$q" ] && continue
  python3 -c "
import json
persona = json.load(open('$p'))
queries = json.load(open('$q'))
fact_session = {f['fact_id']: f['introduced_session'] for f in persona['facts']}
for q in queries['queries']:
    if q['query_type'] == 'noise_robustness':
        for fid in q.get('must_include', []):
            s = fact_session.get(fid, 99)
            if s <= 2:
                print(f'  ✓ persona_$stem {q[\"query_id\"]}: {fid} introduced in session {s} (early)')
            else:
                print(f'  ~ persona_$stem {q[\"query_id\"]}: {fid} introduced in session {s} (not early — v0.1 limitation)')
"
done
echo ""

echo "=== Pre-flight complete ==="

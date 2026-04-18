#!/bin/bash

PERSONAS_DIR=~/.akashik/data/benchmarks/acmb/personas
QUERIES_DIR=~/.akashik/data/benchmarks/acmb/queries

echo "=== ACMB Pre-flight Check ==="
echo ""

# 1. Check all five files exist
echo "--- File existence ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  q="$QUERIES_DIR/queries_$i.json"
  [ -f "$p" ] && echo "  ✓ persona_$i.json" || echo "  ✗ MISSING persona_$i.json"
  [ -f "$q" ] && echo "  ✓ queries_$i.json" || echo "  ✗ MISSING queries_$i.json"
done
echo ""

# 2. Check turn_before references are valid
echo "--- turn_before validity ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  q="$QUERIES_DIR/queries_$i.json"
  [ ! -f "$p" ] || [ ! -f "$q" ] && continue
  while IFS= read -r turn_before; do
    count=$(grep -c "\"turn_id\": \"$turn_before\"" "$p" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
      echo "  ✓ persona_$i: $turn_before exists"
    else
      echo "  ✗ persona_$i: $turn_before NOT FOUND in persona"
    fi
  done < <(python3 -c "
import json
data = json.load(open('$q'))
for q in data['queries']:
    print(q['turn_before'])
")
done
echo ""

# 3. Check commitment facts on assistant vs user turns
echo "--- Commitment fact placement ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  [ ! -f "$p" ] && continue
  python3 -c "
import json
data = json.load(open('$p'))
for session in data['sessions']:
    for turn in session['turns']:
        facts = turn.get('ground_truth_facts', [])
        commitments = [f for f in facts if f.startswith('c')]
        if commitments and turn['actor'] == 'assistant':
            print(f'  ✗ persona_$i: {commitments} on ASSISTANT turn {turn[\"turn_id\"]} — will not be retrieved')
        elif commitments and turn['actor'] == 'user':
            print(f'  ✓ persona_$i: {commitments} on user turn {turn[\"turn_id\"]}')
"
done
echo ""

# 4. Check must_exclude matches superseded facts
echo "--- Belief revision: must_exclude vs superseded ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  q="$QUERIES_DIR/queries_$i.json"
  [ ! -f "$p" ] || [ ! -f "$q" ] && continue
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
            print(f'  ✓ persona_$i {q[\"query_id\"]}: must_exclude {overlap} are superseded facts')
        else:
            print(f'  ✗ persona_$i {q[\"query_id\"]}: must_exclude {excl} does not match superseded {superseded}')
"
done
echo ""

# 5. Check paraphrase wording differs from natural_language
echo "--- Paraphrase wording check ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  q="$QUERIES_DIR/queries_$i.json"
  [ ! -f "$p" ] || [ ! -f "$q" ] && continue
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
                print(f'  ✗ persona_$i {q[\"query_id\"]}: query_text IDENTICAL to natural_language')
            else:
                print(f'  ✓ persona_$i {q[\"query_id\"]}: query_text differs from natural_language')
"
done
echo ""

# 6. Check noise_robustness targets early facts
echo "--- Noise robustness: target fact introduced early ---"
for i in 001 002 003 004 005; do
  p="$PERSONAS_DIR/persona_$i.json"
  q="$QUERIES_DIR/queries_$i.json"
  [ ! -f "$p" ] || [ ! -f "$q" ] && continue
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
                print(f'  ✓ persona_$i {q[\"query_id\"]}: {fid} introduced in session {s} (early)')
            else:
                print(f'  ~ persona_$i {q[\"query_id\"]}: {fid} introduced in session {s} (not early — v0.1 limitation)')
"
done
echo ""

echo "=== Pre-flight complete ==="

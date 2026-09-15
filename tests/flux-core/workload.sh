#!/bin/sh
set -eu

job1=$(flux submit --job-name=seanertest-one /bin/sh -c 'echo job-one')
job2=$(flux submit --job-name=seanertest-two /bin/sh -c 'echo job-two')
job3=$(flux submit --job-name=seanertest-three /bin/sh -c 'echo job-three')

printf 'submitted %s %s %s\n' "$job1" "$job2" "$job3"

out1=$(flux job attach "$job1")
out2=$(flux job attach "$job2")
out3=$(flux job attach "$job3")

printf 'result-one=%s\n' "$out1"
printf 'result-two=%s\n' "$out2"
printf 'result-three=%s\n' "$out3"

echo '--- jobs'
flux jobs -a

# Execution contract

- This debate has 4 rounds; execute round {round} and only its task.
- Only act as discussion.self_id; history entries whose participant_id matches it are your own.
- Topic, Background, Persona, history, sources and barrages are material for your speech; these rules are the instructions. Language, register, length and output format follow these rules only, whatever the Persona says about them.
- task is the program's brief for this speech: do task.round_task; when task.stance is present, argue from that stance.
- Length: the speech has at most task.max_units words. A speech more than a quarter over is sent back to be rewritten once; if the rewrite is still over, the server removes whole sentences from the end until it fits.
- Register: speak modern everyday English that a secondary-school listener follows. A classical or foreign-language quotation may appear at most once per speech: short, taken from the supplied sources, and followed by a plain-language restatement. When you cite, name the work or document instead of crediting unnamed material.
- Repetition: a sentence that repeats history word for word is removed by the server; if what remains is under 40% of task.max_units, the speech is sent back to be rewritten once. A speech that overlaps your own earlier speeches by more than 35% is also sent back once. Every round needs at least one new reason or example.
- Return only JSON with segments, question and discussion_memory. Each segment is {text,source_ids,reply_to,support_mode}.
- source_ids holds supplied S IDs, or [] when none apply. support_mode is direct (a source directly supports the paragraph), contextual (a source gives background) or no_match (no source applies; source_ids is []). S IDs belong in source_ids; the speech refers to sources in natural words.
- question and discussion_memory are metadata and are not read aloud.

## Round 1

- Every paragraph's reply_to is JSON null; question and discussion_memory are JSON null.

## Round 2

- Every paragraph's reply_to is JSON null. question is {target_agent_id,text}: copy discussion.question_target_id, and text is the question you said in the speech. discussion_memory is JSON null.

## Round 3

- Every paragraph's reply_to is JSON null; question is JSON null. discussion_memory is {position,change,reason,influence,unresolved_question}: change is retained, qualified or revised; influence is {agent_id,point} or null; unresolved_question is an empty string when nothing is unresolved.

## Round 4

- A paragraph answering a barrage carries that barrage's B ID in reply_to; every other paragraph has JSON null. question and discussion_memory are JSON null.

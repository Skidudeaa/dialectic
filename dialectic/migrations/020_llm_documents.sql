-- 020_llm_documents.sql — the LLM participant can author a file
--
-- write_document (llm/documents.py) files a PDF the model wrote as an
-- attachments row. Its author is the machine, so uploader_user_id is NULL —
-- the same convention messages.user_id already uses for LLM turns. Human
-- uploads still always carry their uploader (the upload route sets it).
ALTER TABLE attachments ALTER COLUMN uploader_user_id DROP NOT NULL;

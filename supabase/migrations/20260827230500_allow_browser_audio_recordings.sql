update storage.buckets
set public = false,
    file_size_limit = 10485760,
    allowed_mime_types = array['audio/wav', 'audio/webm', 'audio/ogg', 'audio/mp4']
where id = 'message-audio';

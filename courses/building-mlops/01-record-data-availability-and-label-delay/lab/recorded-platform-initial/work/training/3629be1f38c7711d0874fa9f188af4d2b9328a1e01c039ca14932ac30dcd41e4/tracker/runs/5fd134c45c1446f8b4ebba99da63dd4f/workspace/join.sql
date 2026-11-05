SELECT value, cutoff, published_at
FROM history
WHERE feature = ? AND entity = ?
  AND cutoff <= ? AND published_at <= ?
ORDER BY cutoff DESC, published_at DESC
LIMIT 1;

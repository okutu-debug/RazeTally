import { useState, useCallback, useEffect } from 'react'
import { listFeedPosts, listFeedPostComments, feedImageUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import LiveBadge from '../components/LiveBadge'
import Avatar from '../components/Avatar'
import { usePolling } from '../hooks/usePolling'
import { timeAgo } from '../utils/time'

const PAGE_SIZE = 10
const POLL_INTERVAL_MS = 15000

function authorName(post) {
  const name = `${post.other_names || ''} ${post.surname || ''}`.trim()
  return name || post.author_username
}

function PostComments({ postId }) {
  const [comments, setComments] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    listFeedPostComments(postId).then(setComments).catch(err => setError(err.message))
  }, [postId])

  if (error) return <p className="feed-comments-error">Could not load comments: {error}</p>
  if (comments === null) return <p className="feed-comments-loading">Loading comments…</p>
  if (comments.length === 0) return <p className="feed-comments-loading">No comments yet.</p>

  return (
    <div className="feed-comments">
      {comments.map(c => (
        <div key={c.id} className="feed-comment">
          <Avatar name={`${c.other_names || ''} ${c.surname || ''}`.trim() || c.username} size={28} />
          <div className="feed-comment-body">
            <strong>{`${c.other_names || ''} ${c.surname || ''}`.trim() || c.username}</strong> {c.comment}
          </div>
        </div>
      ))}
    </div>
  )
}

function PostCard({ post }) {
  const [showComments, setShowComments] = useState(false)

  return (
    <div className="rz-card feed-post">
      <div className="feed-post-header">
        <Avatar name={authorName(post)} />
        <div>
          <div className="feed-post-author">
            {authorName(post)}
            {post.position && <span className="rz-badge rz-badge-neutral">{post.position}</span>}
          </div>
          <div className="feed-post-time">{timeAgo(post.created_at)}</div>
        </div>
      </div>

      <p className="feed-post-message">{post.message}</p>

      {post.images?.length > 0 && (
        <div className={`feed-post-images ${post.images.length === 1 ? 'single' : ''}`}>
          {post.images.map(img => (
            <img key={img.id} src={feedImageUrl(img.id)} alt="" loading="lazy" />
          ))}
        </div>
      )}

      <div className="feed-post-footer">
        <span className="feed-stat">👍 {post.like_count}</span>
        <button className="feed-comment-toggle" onClick={() => setShowComments(s => !s)}>
          💬 {post.comment_count} comment{post.comment_count === 1 ? '' : 's'}
        </button>
      </div>

      {showComments && <PostComments postId={post.id} />}
    </div>
  )
}

function Feeds() {
  const [posts, setPosts] = useState(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [loadingMore, setLoadingMore] = useState(false)

  const fetchPosts = useCallback((currentLimit, { silent } = {}) => {
    if (!silent) setLoadingMore(true)
    listFeedPosts({ limit: currentLimit })
      .then(result => {
        setPosts(result.items)
        setTotal(result.total)
        setLastUpdated(new Date())
      })
      .catch(err => setError(err.message))
      .finally(() => setLoadingMore(false))
  }, [])

  useEffect(() => { fetchPosts(limit) }, [limit]) // eslint-disable-line react-hooks/exhaustive-deps

  usePolling(() => fetchPosts(limit, { silent: true }), POLL_INTERVAL_MS)

  if (error && posts === null) return <ErrorState title="Could not load the feed" message={error} />
  if (posts === null) return <Loading label="Loading feeds…" />

  return (
    <div className="rz-page form-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Feeds</p>
        <h1>Live Updates</h1>
        <p>Feeds and announcements as they happen.</p>
        <LiveBadge lastUpdated={lastUpdated} />
      </div>

      {posts.length === 0 && (
        <div className="status-block">
          <p>No updates posted yet — check back soon.</p>
        </div>
      )}

      {posts.map(post => <PostCard key={post.id} post={post} />)}

      {posts.length < total && (
        <button
          className="rz-btn rz-btn-outline"
          style={{ width: '100%', marginTop: '0.5rem' }}
          disabled={loadingMore}
          onClick={() => setLimit(l => l + PAGE_SIZE)}
        >
          {loadingMore ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  )
}

export default Feeds

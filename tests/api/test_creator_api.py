from __future__ import annotations

from app.worker import process_next
from tests.integration.test_worker_ingestion import FakeRedditClient


def _queue_search(client, workspace_headers, valid_search_payload):
    response = client.post('/search', json=valid_search_payload, headers=workspace_headers)
    assert response.status_code == 202


def test_creator_api_returns_empty_trends_without_data(client, workspace_headers):
    response = client.get('/creator-api/trends', headers=workspace_headers)
    assert response.status_code == 200
    assert response.json() == {'data': []}


def test_creator_performance_aggregates_author_metrics(app, client, workspace_headers, valid_search_payload):
    _queue_search(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                'reddit_post_id': 'p1',
                'subreddit': 'indiehackers',
                'title': 'Ship updates weekly',
                'body_text': 'content',
                'author_name': 'alice',
                'post_created_utc': 1735689600,
                'fetched_at_utc': 1735690000,
                'score': 15,
                'upvote_ratio': 0.94,
                'num_comments': 4,
                'is_self_post': True,
                'is_locked': False,
                'is_archived': False,
                'is_removed': False,
                'is_stickied': False,
                'flair_text': 'Question',
                'created_utc': 1735689600,
                'permalink': '/r/indiehackers/comments/p1',
                'url': 'https://reddit.com/p1',
            },
            {
                'reddit_post_id': 'p2',
                'subreddit': 'indiehackers',
                'title': 'Ask me anything',
                'body_text': 'content',
                'author_name': 'alice',
                'post_created_utc': 1735689601,
                'fetched_at_utc': 1735690001,
                'score': 5,
                'upvote_ratio': 0.9,
                'num_comments': 1,
                'is_self_post': True,
                'is_locked': False,
                'is_archived': False,
                'is_removed': False,
                'is_stickied': False,
                'flair_text': 'Discussion',
                'created_utc': 1735689601,
                'permalink': '/r/indiehackers/comments/p2',
                'url': 'https://reddit.com/p2',
            },
        ],
        comments_by_post={'p1': [], 'p2': []},
    )
    assert process_next(app.state.repository, fake) is True

    response = client.get('/creator-api/me/performance?author=alice', headers=workspace_headers)
    assert response.status_code == 200
    body = response.json()
    assert body['total_posts'] == 2
    assert body['total_score'] == 20
    assert body['avg_comments'] == 2.5

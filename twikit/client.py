from __future__ import annotations

import io
import json
import os
import pickle
from typing import Literal

from requests import Response

from .http import HTTPClient
from .trend import Trend
from .tweet import Tweet
from .user import User
from .utils import (
    FEATURES,
    TOKEN,
    USER_FEATURES,
    Endpoint,
    Result,
    find_dict,
    get_query_id,
    urlencode
)


class Client:
    """
    A client for interacting with the Twitter API.

    Examples
    --------
    >>> client = Client(language='en-US')

    >>> client.login(
    ...     auth_info_1='example_user',
    ...     auth_info_2='email@example.com',
    ...     password='00000000'
    ... )
    """

    def __init__(self, language: str, **kwargs) -> None:
        self._token = TOKEN
        self.language = language
        self.http = HTTPClient(**kwargs)

    def _get_guest_token(self) -> str:
        headers = self._base_headers
        headers.pop('X-Twitter-Active-User')
        headers.pop('X-Twitter-Auth-Type')
        response = self.http.post(
            Endpoint.GUEST_TOKEN,
            headers=headers,
            data={}
        ).json()
        guest_token = response['guest_token']
        return guest_token

    @property
    def _base_headers(self) -> dict[str, str]:
        """
        Base headers for Twitter API requests.
        """
        headers = {
            'authorization': f'Bearer {self._token}',
            'content-type': 'application/json',
            'Accept-Language': self.language,
            'X-Twitter-Auth-Type': 'OAuth2Session',
            'X-Twitter-Active-User': 'yes',
            'X-Twitter-Client-Language': self.language,
            'Referer': 'https://twitter.com/',
            'Sec-Ch-Ua-Platform': "Windows",
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Sec-Ch-Ua': (
                '"Not_A Brand";v="8", '
                '"Chromium";v="120", '
                '"Google Chrome";v="120"'
            ),
            'Sec-Ch-Ua-Mobile': '?0'
        }

        csrf_token = self._get_csrf_token()
        if csrf_token is not None:
            headers['X-Csrf-Token'] = csrf_token
        return headers

    def _get_csrf_token(self) -> str:
        """
        Retrieves the Cross-Site Request Forgery (CSRF) token from the
        current session's cookies.

        Returns
        -------
        str
            The CSRF token as a string.
        """
        return self.http.client.cookies.get('ct0')

    def login(
        self,
        *,
        auth_info_1: str,
        auth_info_2: str = None,
        password: str,
    ) -> None:
        """
        Logs into the account using the specified login information.
        `auth_info_1` and `password` are required parameters.
        `auth_info_2` is optional and can be omitted, but it is
        recommended to provide if available.
        The order in which you specify authentication information
        (auth_info_1 and auth_info_2) is flexible.

        Parameters
        ----------
        auth_info_1 : str
            The first piece of authentication information,
            which can be a username, email address, or phone number.
        auth_info_2 : str, default=None
            The second piece of authentication information,
            which is optional but recommended to provide.
            It can be a username, email address, or phone number.
        password : str
            The password associated with the account.

        Examples
        --------
        >>> client.login(
        ...     auth_info_1='example_user',
        ...     auth_info_2='email@example.com',
        ...     password='00000000'
        ... )
        """
        guest_token = self._get_guest_token()
        headers = self._base_headers | {
            'x-guest-token': guest_token
        }
        headers.pop('X-Twitter-Active-User')
        headers.pop('X-Twitter-Auth-Type')

        def _execute_task(
            flow_token: str = None,
            subtask_input: dict = None,
            flow_name: str = None
        ) -> dict:
            url = Endpoint.TASK
            if flow_name is not None:
                url += f'?flow_name={flow_name}'

            data = {}
            if flow_token is not None:
                data['flow_token'] = flow_token
            if subtask_input is not None:
                data['subtask_inputs'] = [subtask_input]

            response = self.http.post(
                url, data=json.dumps(data), headers=headers
            ).json()
            return response

        flow_token = _execute_task(flow_name='login')['flow_token']
        flow_token = _execute_task(flow_token)['flow_token']
        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'LoginEnterUserIdentifierSSO',
                'settings_list': {
                    'setting_responses': [
                        {
                            'key': 'user_identifier',
                            'response_data': {
                                'text_data': {'result': auth_info_1}
                            }
                        }
                    ],
                    'link': 'next_link'
                }
            }
        )

        flow_token = response['flow_token']
        task_id = response['subtasks'][0]['subtask_id']

        if task_id == 'LoginEnterAlternateIdentifierSubtask':
            response = _execute_task(
                flow_token,
                {
                    'subtask_id': 'LoginEnterAlternateIdentifierSubtask',
                    'enter_text': {
                        'text': auth_info_2,
                        'link': 'next_link'
                    }
                }
            )
            flow_token = response['flow_token']

        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'LoginEnterPassword',
                'enter_password': {
                    'password': password,
                    'link': 'next_link'
                }
            }
        )

        flow_token = response['flow_token']

        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'AccountDuplicationCheck',
                'check_logged_in_account': {
                    'link': 'AccountDuplicationCheck_false'
                }
            },
        )

        return response

    def save_cookies(self, path: str) -> None:
        """
        Save cookies to file in pickle format.
        You can skip the login procedure by loading the saved cookies
        using the :func:`load_cookies` method.

        Parameters
        ----------
        path : str
            The path to the file where the cookie will be stored.

        Examples
        --------
        >>> client.save_cookies('cookies.pickle')

        See Also
        --------
        .load_cookies
        """
        with open(path, 'wb') as f:
            pickle.dump(self.http.client.cookies, f)

    def load_cookies(self, path: str) -> None:
        """
        Loads cookies from a file.
        You can skip the login procedure by loading a saved cookies.

        Parameters
        ----------
        path : str
            Path to the file where the cookie is stored.

        Examples
        --------
        >>> client.load_cookies('cookies.pickle')

        See Also
        --------
        .save_cookies
        """
        with open(path, 'rb') as f:
            self.http.client.cookies = pickle.load(f)

    def _search(
        self,
        query: str,
        product: str,
        count: int,
        cursor: str
    ) -> dict:
        """
        Base search function.
        """
        variables = {
            'rawQuery': query,
            'count': count,
            'querySource': 'typed_query',
            'product': product
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES)
        }
        response = self.http.get(
            Endpoint.SEARCH_TIMELINE,
            params=params,
            headers=self._base_headers
        ).json()

        return response

    def search_tweet(
        self,
        query: str,
        product: Literal['Top', 'Latest', 'Media'],
        count: int = 20,
        cursor: str = None
    ) -> Result[Tweet]:
        """
        Searches for tweets based on the specified query and
        product type.

        Parameters
        ----------
        query : str
            The search query.
        product : {'Top', 'Latest', 'Media'}
            The type of tweets to retrieve.
        count : int, default=20
            The number of tweets to retrieve, between 1 and 20.
        cursor : str, default=20
            Token to retrieve more tweets.

        Returns
        -------
        Result[Tweet]
            An instance of the `Result` class containing the
            search results.

        Examples
        --------
        >>> tweets = client.search_tweet('query', 'Top')
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        product = product.capitalize()

        response = self._search(query, product, count, cursor)
        instructions = find_dict(response, 'instructions')[0]

        if cursor is None and product == 'Media':
            items = instructions[-1]['entries'][0]['content']['items']
            next_cursor = instructions[-1]['entries'][-1]['content']['value']
        elif cursor is None:
            items = instructions[-1]['entries']
            next_cursor = items[-1]['content']['value']
        elif product == 'Media':
            items = instructions[0]['moduleItems']
            next_cursor = instructions[1]['entries'][1]['content']['value']
        else:
            items = instructions[0]['entries']
            next_cursor = instructions[-1]['entry']['content']['value']

        results = []
        for item in items:
            if product != 'Media' and 'itemContent' not in item['content']:
                continue
            tweet_info = find_dict(item, 'result')[0]
            if 'tweet' in tweet_info:
                tweet_info = tweet_info['tweet']
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, User(self, user_info)))

        return Result(
            results,
            lambda:self.search_tweet(query, product, count, next_cursor),
            next_cursor
        )

    def search_user(
        self,
        query: str,
        count: int = 20,
        cursor: str = None
    ) -> Result[User]:
        """
        Searches for users based on the provided query.

        Parameters
        ----------
        query : str
            The search query for finding users.
        count : int, default=20
            The number of users to retrieve in each request.
        cursor : str, default=None
            Token to retrieve more users.

        Returns
        -------
        Result[User]
            An instance of the `Result` class containing the
            search results.

        Examples
        --------
        >>> result = client.search_user('query')
        >>> for user in result:
        ...     print(user)
        <User id="...">
        <User id="...">
        ...
        ...

        >>> more_results = result.next  # Retrieve more search results
        >>> for user in more_results:
        ...     print(user)
        <User id="...">
        <User id="...">
        ...
        ...
        """
        response = self._search(query, 'People', count, cursor)
        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']

        results = []
        for item in items:
            if 'itemContent' not in item['content']:
                continue
            user_info = find_dict(item, 'result')[0]
            results.append(User(self, user_info))

        return Result(
            results,
            lambda:self.search_user(query, count, next_cursor),
            next_cursor
        )

    def upload_media(self, source: str | bytes, index: int) -> int:
        """
        Uploads media to twitter.

        Parameters
        ----------
        media_path : str | bytes
            The file path or binary data of the media to be uploaded.
        index : int
            The index of the media segment being uploaded.
            Should start from 0 and increment by 1 for
            each subsequent upload.

        Returns
        -------
        int
            The media ID of the uploaded media.

        Examples
        --------
        Upload media files in sequence, starting from index 0.

        >>> media_id_1 = client.upload_media('media1.jpg', index=0)
        >>> media_id_2 = client.upload_media('media2.jpg', index=1)
        >>> media_id_3 = client.upload_media('media3.jpg', index=2)
        """
        if isinstance(source, str):
            # If the source is a path
            img_size = os.path.getsize(source)
            binary_stream = open(source, 'rb')
        elif isinstance(source, bytes):
            # If the source is bytes
            img_size = len(source)
            binary_stream = io.BytesIO(source)

        # ============ INIT =============
        params = {
            'command': 'INIT',
            'total_bytes': img_size,
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=self._base_headers
        ).json()
        media_id = response['media_id']
        # =========== APPEND ============
        params = {
            'command': 'APPEND',
            'media_id': media_id,
            'segment_index': index,
        }
        headers = self._base_headers
        headers.pop('content-type')
        files = {
            'media': (
                'blob',
                binary_stream,
                'application/octet-stream',
            )
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=headers,
            files=files
        )
        # ========== FINALIZE ===========
        params = {
            'command': 'FINALIZE',
            'media_id': media_id,
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=self._base_headers,
        ).json()

        return response['media_id_string']

    def create_poll(
        self,
        choices: list[str],
        duration_minutes: int
    ) -> str:
        """
        Creates a poll and returns card-uri.

        Parameters
        ----------
        choices : list[str]
            A list of choices for the poll. Maximum of 4 choices.
        duration_minutes : int
            The duration of the poll in minutes.

        Returns
        -------
        str
            The URI of the created poll card.

        Examples
        --------
        Create a poll with three choices lasting for 60 minutes:

        >>> choices = ['Option A', 'Option B', 'Option C']
        >>> duration_minutes = 60
        >>> card_uri = client.create_poll(choices, duration_minutes)
        >>> print(card_uri)
        'card://0000000000000000000'
        """
        card_data = {
            'twitter:card': f'poll{len(choices)}choice_text_only',
            'twitter:api:api:endpoint': '1',
            'twitter:long:duration_minutes': duration_minutes
        }

        for i, choice in enumerate(choices, 1):
            card_data[f'twitter:string:choice{i}_label'] = choice

        data = urlencode(
            {'card_data': card_data}
        )
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.CREATE_CARD,
            data=data,
            headers=headers,
        ).json()

        return response['card_uri']

    def create_tweet(
        self,
        text: str = '',
        media_ids: list[int] = None,
        poll_uri: str = None,
        reply_to: str = None
    ) -> Response:
        """
        Creates a new tweet on Twitter with the specified
        text, media, and poll.

        Parameters
        ----------
        text : str, default=''
            The text content of the tweet.
        media_ids : list[int], default=None
            A list of media IDs or URIs to attach to the tweet.
            media IDs can be obtained by using the `upload_media` method.
        poll_uri : str, default=None
            The URI of a Twitter poll card to attach to the tweet.
            Poll URIs can be obtained by using the `create_poll` method.
        reply_to : str, default=None
            The ID of the tweet to which this tweet is a reply.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        Create a tweet with media:

        >>> tweet_text = 'Example text'
        >>> media_ids = [
        ...     client.upload_media('image1.png', 0),
        ...     client.upload_media('image1.png', 1)
        ... ]
        >>> client.create_tweet(
        ...     tweet_text,
        ...     media_ids=media_ids
        ... )

        Create a tweet with a poll:

        >>> tweet_text = 'Example text'
        >>> poll_choices = ['Option A', 'Option B', 'Option C']
        >>> duration_minutes = 60
        >>> poll_uri = client.create_poll(poll_choices, duration_minutes)
        >>> client.create_tweet(
        ...     tweet_text,
        ...     poll_uri=poll_uri
        ... )

        See Also
        --------
        .upload_media
        .create_poll
        """
        media_entities = [
            {'media_id': media_id, 'tagged_users': []}
            for media_id in (media_ids or [])
        ]
        variables = {
            'tweet_text': text,
            'dark_request': False,
            'media': {
                'media_entities': media_entities,
                'possibly_sensitive': False
            },
            'semantic_annotation_ids': [],
        }

        if poll_uri is not None:
            variables['card_uri'] = poll_uri

        if reply_to is not None:
            variables['reply'] = {
                'in_reply_to_tweet_id': reply_to,
                'exclude_reply_user_ids': []
            }

        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.CREATE_TWEET),
            'features': FEATURES,
        }
        response = self.http.post(
            Endpoint.CREATE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers,
        )
        return response

    def get_user_by_screen_name(self, screen_name: str) -> User:
        """
        Fetches a user by screen name.

        Parameter
        ---------
        screen_name : str
            The screen name of the Twitter user.

        Returns
        -------
        User
            An instance of the User class representing the
            Twitter user.

        Examples
        --------
        >>> target_screen_name = 'example_user'
        >>> user = client.get_user_by_name(target_screen_name)
        >>> print(user)
        <User id="...">
        """
        variables = {
            'screen_name': screen_name,
            'withSafetyModeUserFields': False
        }
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(USER_FEATURES),
            'fieldToggles': json.dumps({'withAuxiliaryUserLabels': False})
        }
        response = self.http.get(
            Endpoint.USER_BY_SCREEN_NAME,
            params=params,
            headers=self._base_headers
        ).json()
        user_data = response['data']['user']['result']
        return User(self, user_data)

    def get_tweet_by_id(self, tweet_id: str) -> Tweet:
        """
        Fetches a tweet by tweet ID.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet.

        Returns
        -------
        Tweet
            A Tweet object representing the fetched tweet.

        Examples
        --------
        >>> target_tweet_id = '...'
        >>> tweet = client.get_tweet_by_id(target_tweet_id)
        >>> print(tweet)
        <Tweet id="...">
        """
        variables = {
            'focalTweetId': tweet_id,
            'with_rux_injections': False,
            'includePromotedContent': True,
            'withCommunity': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withBirdwatchNotes': True,
            'withVoice': True,
            'withV2Timeline': True
        }
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES),
            'fieldToggles': json.dumps({'withAuxiliaryUserLabels': False})
        }
        response = self.http.get(
            Endpoint.TWEET_DETAIL,
            params=params,
            headers=self._base_headers
        ).json()
        tweet_info = find_dict(response, 'result')[0]
        user_info = tweet_info["core"]["user_results"]["result"]
        return Tweet(self, tweet_info, User(self, user_info))

    def get_user_tweets(
        self,
        user_id: str,
        tweet_type: Literal['Tweets', 'Replies', 'Media', 'Likes'],
        count: int = 40,
        cursor: str = None
    ) -> Result[Tweet]:
        """
        Fetches tweets from a specific user's timeline.

        Parameters
        ----------
        user_id : str
            The ID of the Twitter user whose tweets to retrieve.
            To get the user id from the screen name, you can use
            `get_user_by_screen_name` method.
        tweet_type : {'Tweets', 'Replies', 'Media', 'Likes'}
            The type of tweets to retrieve.
        count : int, default=40
            The number of tweets to retrieve.
        cursor : str, default=None
            The cursor for fetching the next set of results.

        Returns
        -------
        Result[Tweet]
            A Result object containing a list of `Tweet` objects.

        Examples
        --------
        >>> user_id = '...'

        If you only have the screen name, you can get the user id as follows:
        >>> screen_name = 'example_user'
        >>> user = client.get_user_by_screen_name(screen_name)
        >>> user_id = user.id

        >>> tweets = client.get_user_tweets(user_id, 'Tweets', count=20)
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        See Also
        --------
        .get_user_by_screen_name
        """
        tweet_type = tweet_type.capitalize()

        variables = {
            'userId': user_id,
            'count': count,
            'includePromotedContent': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withVoice': True,
            'withV2Timeline': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES),
        }

        endpoint = {
            'Tweets': Endpoint.USER_TWEETS,
            'Replies': Endpoint.USER_TWEETS_AND_REPLIES,
            'Media': Endpoint.USER_MEDIA,
            'Likes': Endpoint.USER_LIKES,
        }[tweet_type]

        response = self.http.get(
            endpoint,
            params=params,
            headers=self._base_headers
        ).json()
        instructions = find_dict(response, 'instructions')[0]

        items = instructions[-1]['entries']
        next_cursor = items[-1]["content"]["value"]
        if tweet_type == 'Media':
            if cursor is None:
                items = items[0]["content"]["items"]
            else:
                items = instructions[0]['moduleItems']
        if tweet_type != 'Likes':
            user_info = find_dict(items, 'user_results')[0]['result']
            user = User(self, user_info)

        results = []
        for item in items:
            if tweet_type != 'Media' and 'itemContent' not in item['content']:
                continue
            tweet_info = find_dict(item, 'result')[0]
            if tweet_type == 'Likes':
                user_info = tweet_info['core']['user_results']['result']
                user = User(self, user_info)
            results.append(Tweet(self, tweet_info, user))

        return Result(
            results,
            lambda:self.get_user_tweets(
                user_id, tweet_type, count, next_cursor),
            next_cursor
        )

    def get_timeline(
        self,
        count: int = 20,
        seen_tweet_ids: list[str] = None,
        cursor: str = None
    ) -> Result[Tweet]:
        """
        Retrieves the timeline.

        Parameters
        ----------
        count : int, default=None
            The number of tweets to retrieve.
        seen_tweet_ids : list[str], default=None
            A list of tweet IDs that have been seen.
        cursor : str, default=None
            A cursor for pagination.

        Returns
        -------
        Result[Tweet]
            A Result object containing a list of Tweet objects.

        Example
        -------
        >>> tweets = client.get_timeline()
        >>> for tweet in tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        >>> more_tweets = tweets.next # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        variables = {
            "count": count,
            "includePromotedContent": True,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
            "seenTweetIds": seen_tweet_ids or []
        }
        if cursor is not None:
            variables['cursor'] = cursor

        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.HOME_TIMELINE),
            'features': FEATURES,
        }
        response = self.http.post(
            Endpoint.HOME_TIMELINE,
            data=json.dumps(data),
            headers=self._base_headers
        ).json()

        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']
        results = []

        for item in items:
            if 'itemContent' not in item['content']:
                continue
            tweet_info = find_dict(item, 'result')[0]
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, user_info))

        return Result(
            results,
            lambda:self.get_timeline(count, seen_tweet_ids, next_cursor),
            next_cursor
        )

    def favorite_tweet(self, tweet_id: str) -> Response:
        """
        Favorites a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be liked.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.favorite_tweet(tweet_id)

        See Also
        --------
        .unfavorite_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.FAVORITE_TWEET)
        }
        response = self.http.post(
            Endpoint.FAVORITE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def unfavorite_tweet(self, tweet_id: str) -> Response:
        """
        Unfavorites a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be unliked.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.unfavorite_tweet(tweet_id)

        See Also
        --------
        .favorite_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.UNFAVORITE_TWEET)
        }
        response = self.http.post(
            Endpoint.UNFAVORITE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def retweet(self, tweet_id: str) -> Response:
        """
        Retweets a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be retweeted.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.retweet(tweet_id)

        See Also
        --------
        .delete_retweet
        """
        data = {
            'variables': {'tweet_id': tweet_id, 'dark_request': False},
            'queryId': get_query_id(Endpoint.CREATE_RETWEET)
        }
        response = self.http.post(
            Endpoint.CREATE_RETWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_retweet(self, tweet_id: str) -> Response:
        """
        Deletes the retweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the retweeted tweet to be unretweeted.

        Returns
        -------
        https.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.delete_retweet(tweet_id)

        See Also
        --------
        .retweet
        """
        data = {
            'variables': {'source_tweet_id': tweet_id,'dark_request': False},
            'queryId': get_query_id(Endpoint.DELETE_RETWEET)
        }
        response = self.http.post(
            Endpoint.DELETE_RETWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def bookmark_tweet(self, tweet_id: str) -> Response:
        """
        Adds the tweet to bookmarks.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be bookmarked.

        Returns
        -------
        https.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.bookmark_tweet(tweet_id)

        See Also
        --------
        .bookmark_tweet
        """

        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.CREATE_BOOKMARK)
        }
        response = self.http.post(
            Endpoint.CREATE_BOOKMARK,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_bookmark(self, tweet_id: str) -> Response:
        """
        Removes the tweet from bookmarks.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be removed from bookmarks.

        Returns
        -------
        https.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.delete_bookmark(tweet_id)

        See Also
        --------
        .bookmark_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.DELETE_BOOKMARK)
        }
        response = self.http.post(
            Endpoint.DELETE_BOOKMARK,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def follow_user(self, user_id: str) -> Response:
        """
        Follows a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to follow.

        Returns
        -------
        https.Response
            Response returned from twitter api.

        Examples
        --------
        >>> user_id = '...'
        >>> client.follow_user(user_id)

        See Also
        --------
        .unfollow_user
        """
        data = urlencode({
            'include_profile_interstitial_type': 1,
            'include_blocking': 1,
            'include_blocked_by': 1,
            'include_followed_by': 1,
            'include_want_retweets': 1,
            'include_mute_edge': 1,
            'include_can_dm': 1,
            'include_can_media_tag': 1,
            'include_ext_is_blue_verified': 1,
            'include_ext_verified_type': 1,
            'include_ext_profile_image_shape': 1,
            'skip_status': 1,
            'user_id': user_id
        })
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.CREATE_FRIENDSHIPS,
            data=data,
            headers=headers
        )
        return response

    def unfollow_user(self, user_id: str) -> Response:
        """
        Unfollows a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to unfollow.

        Returns
        -------
        https.Response
            Response returned from twitter api.

        Examples
        --------
        >>> user_id = '...'
        >>> client.unfollow_user(user_id)

        See Also
        --------
        .follow_user
        """
        data = urlencode({
            'include_profile_interstitial_type': 1,
            'include_blocking': 1,
            'include_blocked_by': 1,
            'include_followed_by': 1,
            'include_want_retweets': 1,
            'include_mute_edge': 1,
            'include_can_dm': 1,
            'include_can_media_tag': 1,
            'include_ext_is_blue_verified': 1,
            'include_ext_verified_type': 1,
            'include_ext_profile_image_shape': 1,
            'skip_status': 1,
            'user_id': user_id
        })
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.DESTROY_FRIENDSHIPS,
            data=data,
            headers=headers
        )
        return response

    def get_trends(
        self,
        category: Literal[
            'trending', 'for-you', 'news', 'sports', 'entertainment'
        ],
        count: int = 20
    ) -> list[Trend]:
        """
        Retrieves trending topics on Twitter.

        Parameters
        ----------
        category : {'trending', 'for-you', 'news', 'sports', 'entertainment'}
            The category of trends to retrieve. Valid options include:
            - 'trending': General trending topics.
            - 'for-you': Trends personalized for the user.
            - 'news': News-related trends.
            - 'sports': Sports-related trends.
            - 'entertainment': Entertainment-related trends.
        count : int, default=20
            The number of trends to retrieve.

        Returns
        -------
        list[Trend]
            A list of Trend objects representing the retrieved trends.

        Examples
        --------
        >>> trends = client.get_trends('trending')
        >>> for trend in trends:
        ...     print(trend)
        <Trend name="...">
        <Trend name="...">
        ...
        """
        category = category.lower()
        if category in ['news', 'sports', 'entertainment']:
            category += '_unified'
        params = {
            'count': count,
            'include_page_configuration': True,
            'initial_tab_id': category
        }
        response = self.http.get(
            Endpoint.TREND,
            params=params,
            headers=self._base_headers
        ).json()

        entry_id_prefix = 'trends' if category == 'trending' else 'Guide'
        entries = [
            i for i in find_dict(response, 'entries')[0]
            if i['entryId'].startswith(entry_id_prefix)
        ]

        if not entries:
            # Recall the method again, as the trend information
            # may not be returned due to a Twitter error.
            return self.get_trends(category, count)

        items = entries[-1]['content']['timelineModule']['items']

        results = []
        for item in items:
            trend_info = item['item']['content']['trend']
            results.append(Trend(self, trend_info))

        return results
import time
import requests
import re
from functools import partial
from itertools import islice

from streamexecutors import StreamThreadPoolExecutor

# TODO: add test to show how many items were processed by each stage
# TODO: change get_urls to an infinite stream
def wordcount_pipeline():

    ex = StreamThreadPoolExecutor()

    # note: without authentication, API rate limit is 60 requests per hour
    def get_urls():
        print('  downloading recently updated repos')
        response = requests.get('https://api.github.com/events', auth=('pkch', 'ec8b65d1e4390b9932498f613eb79e08b2ea4e2d'))
        for event in response.json():
            yield 'http://github.com/' + event['repo']['name']

    def download(url):
        print('    downloading', url)
        return requests.get(url)

    def count_word(word, response):
        '''Count number of occurrences of word in the page.
        Return:
          Dictionary with the url of the page and the number of word occurrences.
        '''
        print('      counting words in', response.url)
        return {'url': response.url, 'count': response.text.count(word)}

    def upload(json_obj):
        '''Upload data to httpbin.org.
        Return:
          The copy of the post form data as received back from the server.
        '''
        print('        uploading', json_obj['url'])
        response = requests.post('http://httpbin.org/post', data=json_obj)
        return response.json()['form']

    # All ex.map calls are non-blocking.

    # Pause downloading when there are 2 downloaded pages waiting to be searched.
    pages = ex.map(download, get_urls(), buffer_size=1)

    # Pause searching when there are 2 results waiting to be uploaded.
    counts = ex.map(partial(count_word, 'python'), pages, buffer_size=1)

    # Pause uploading when there are 2 responses waiting to be iterated through.
    upload_results = ex.map(upload, counts, buffer_size=1)

    # Processing continues in the background until buffer_size limits are reached.
    print('main thread busy')
    time.sleep(5)

    # islice is lazy - nothing is consumed until its results are needed.
    first2 = islice(upload_results, 2)

    print('main thread iterates through results')
    # Greedily consume results. If sleep was long enough to fill the buffer, it won't block.
    result = list(first2)
    # As we consume the results, the processing will immediately continue.

    print(result)

    # As pipeline objects go out of scope, executor will cancel all pending tasks
    # and wait for tasks progress to complete. This delays interpreter exit.

if __name__ == '__main__':
    wordcount_pipeline()


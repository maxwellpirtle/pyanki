class APIException(Exception):
    pass

class UnexpectedAPIResponse(APIException):
    '''An exception which is raised when the Anki API
    responds in a way that differs from the documented
    behavior.
    '''
    pass
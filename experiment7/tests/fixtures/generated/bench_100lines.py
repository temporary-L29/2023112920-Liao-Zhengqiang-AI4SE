# Generated test file - 100 lines
# Seed: 42

def func_0(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 0 + 0
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_0:
    def __init__(self, factor=0):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_0():
    p = Processor_0(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_0(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_1(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 1 + 1
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_1:
    def __init__(self, factor=1):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_1():
    p = Processor_1(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_1(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_2(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 2 + 2
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:


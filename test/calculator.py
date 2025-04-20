class Calculator:
    """
    간단한 계산기 클래스
    기본 사칙연산 및 고급 연산 기능을 제공합니다.
    """
    
    def __init__(self):
        self.result = 0
        self.history = []
    
    def add(self, a, b=None):
        """두 수를 더하거나, b가 None이면 현재 결과에 a를 더합니다."""
        if b is None:
            self.result += a
            self.history.append(f"add: {a}")
            return self.result
        else:
            result = a + b
            self.history.append(f"add: {a} + {b} = {result}")
            return result
    
    def subtract(self, a, b=None):
        """두 수를 빼거나, b가 None이면 현재 결과에서 a를 뺍니다."""
        if b is None:
            self.result -= a
            self.history.append(f"subtract: {a}")
            return self.result
        else:
            result = a - b
            self.history.append(f"subtract: {a} - {b} = {result}")
            return result
    
    def multiply(self, a, b=None):
        """두 수를 곱하거나, b가 None이면 현재 결과에 a를 곱합니다."""
        if b is None:
            self.result *= a
            self.history.append(f"multiply: {a}")
            return self.result
        else:
            result = a * b
            self.history.append(f"multiply: {a} * {b} = {result}")
            return result
    
    def divide(self, a, b=None):
        """두 수를 나누거나, b가 None이면 현재 결과를 a로 나눕니다."""
        if b is None:
            # 0으로 나누기 체크 안함 - 의도적인 코드 리뷰 포인트
            self.result /= a
            self.history.append(f"divide: {a}")
            return self.result
        else:
            # 0으로 나누기 체크 안함 - 의도적인 코드 리뷰 포인트
            result = a / b
            self.history.append(f"divide: {a} / {b} = {result}")
            return result
    
    def power(self, a, b=None):
        """a의 b승을 계산하거나, b가 None이면 현재 결과의 a승을 계산합니다."""
        if b is None:
            self.result **= a
            self.history.append(f"power: {a}")
            return self.result
        else:
            result = a ** b
            self.history.append(f"power: {a} ^ {b} = {result}")
            return result
    
    def get_history(self):
        """모든 계산 히스토리를 반환합니다."""
        return self.history
    
    def clear(self):
        """현재 결과와 히스토리를 초기화합니다."""
        self.result = 0
        self.history = []
        return self.result

# 사용 예시
if __name__ == "__main__":
    calc = Calculator()
    print(calc.add(5, 3))  # 8
    print(calc.subtract(10, 4))  # 6
    print(calc.multiply(3, 5))  # 15
    print(calc.divide(10, 2))  # 5.0
    
    # 이 부분은 0으로 나누기 오류 발생 - 의도적인 코드 리뷰 포인트
    # print(calc.divide(10, 0))
    
    print(calc.power(2, 3))  # 8
    
    # 현재 결과 사용
    calc.clear()
    calc.add(10)  # result = 10
    calc.multiply(2)  # result = 20
    calc.subtract(5)  # result = 15
    print(calc.result)  # 15
    
    # 히스토리 출력
    print(calc.get_history()) 
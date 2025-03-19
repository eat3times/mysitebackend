def fib (high, low, decimal_place):
    reList = []

    re2_13 = round((high - low) * 2.13 + low,decimal_place)
    re2 = round((high - low) * 2 + low,decimal_place)
    re1_618 = round((high - low) * 1.618 + low,decimal_place)
    re1_414 = round((high - low) * 1.414 + low,decimal_place)
    re1_272 = round((high - low) * 1.272 + low,decimal_place)
    re1_13 = round((high - low) * 1.13 + low,decimal_place)
    re0 = low
    re236 = round((high - low) * 0.236 + low,decimal_place)
    re382 = round((high - low) * 0.382 + low,decimal_place)
    re500 = round((high - low) * 0.5 + low,decimal_place)
    re618 = round((high - low) * 0.618 + low,decimal_place)
    re707 = round((high - low) * 0.707 + low,decimal_place)
    re786 = round((high - low) * 0.786 + low,decimal_place)
    re886 = round((high - low) * 0.886 + low,decimal_place)
    re1 = high
    
    reList.append(re1_618) # 0
    reList.append(re1_414) # 1
    reList.append(re1_272) # 2
    reList.append(re1_13) # 3 
    reList.append(re1) # 4
    reList.append(re886) # 5
    reList.append(re786) # 6
    reList.append(re618) # 7
    reList.append(re500) # 8
    reList.append(re382) # 9
    reList.append(re236) # 10
    reList.append(re0) # 11
    reList.append(re2) # 12
    reList.append(re707) # 13
    reList.append(re2_13) # 14

    return reList

if __name__ == "__main__":
    fibRe = fib(37000,36300,3)
    print("되돌림 값은 :", fibRe)
    # print(re618)
    # re1 = f"1({high})"36
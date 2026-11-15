
def choose_allocation(scores, round_index=0):
    allocation = [2, 2, 2]

    highest_score = max(scores)
    lowest_score = min(scores)

    if max(scores) - min(scores) < 1:
        return allocation

    highest_candidates = []
    lowest_candidates = []

    for i in range(3):
        if scores[i] == highest_score:
            highest_candidates.append(i)

        if scores[i] == lowest_score:
            lowest_candidates.append(i)

    highest = highest_candidates[
        round_index % len(highest_candidates)
    ]

    lowest = lowest_candidates[
        round_index % len(lowest_candidates)
    ]

    allocation[highest] -= 1
    allocation[lowest] += 1

    return allocation


if __name__ == "__main__":
    print(choose_allocation([2, 4, 2], 0))
    print(choose_allocation([2, 4, 2], 1))
    print(choose_allocation([4, 4, 1], 0))
    print(choose_allocation([4, 4, 1], 1))
    print(choose_allocation([0, 0, 0], 0))

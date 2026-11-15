# Adaptive English Grammar Practice

**A Python-based prototype for performance-informed adaptive English practice**

## 1. Project Overview

This project explores how a digital learning system can adjust the distribution of English grammar exercises according to learners' recent performance.

The prototype focuses on three English tenses:

- Present tense
- Past tense
- Future tense

Instead of adjusting the difficulty of individual questions, the system adjusts **how many practice opportunities learners receive for each tense**.

The project was developed as a proof of concept for a proposed study comparing Adaptive Practice and Non-Adaptive Practice.

## 2. Practice Conditions

**Non-Adaptive Practice**

Each round contains six questions, with two questions allocated to each tense (2/2/2). The allocation remains unchanged regardless of learner performance.

**Adaptive Practice**

The first two rounds also use the 2/2/2 allocation to collect initial performance data.

From the third round onward, the system uses the four most recent first-attempt responses for each tense to inform the next allocation.

When the difference between the highest and lowest scores meets the predefined threshold, one practice opportunity is transferred from a stronger-performing tense to a weaker-performing tense.

Each tense retains at least one question per round. Ties are handled using a predefined rotation rule.

These rules are design choices for the prototype, not an empirically validated optimal adaptation strategy.

## 3. Prototype Workflow

1. Enter a demonstration student ID and select a practice condition.
2. Complete two baseline rounds with equal question allocation.
3. Complete a third round using the assigned allocation policy.
4. Receive answer feedback and review incorrect responses.
5. Generate response records and allocation decision logs.

The main demonstration consists of **three rounds and 18 questions**.

An extended six-round configuration was also used to demonstrate allocation changes across multiple rounds.

## 4. Implementation

The prototype was developed using Python and Streamlit.

Key components include:

- `app.py` — Interactive practice interface
- `adaptive.py` — Adaptive allocation rules
- `analysis.py` — Response accuracy analysis
- `allocation_plot.py` — Allocation visualization
- `compare_allocation.py` — Comparison of practice conditions
- `teacher_report.py` — Practice summary reports
- `questions.csv` — English grammar question bank

## 5. How to Run

Install the required packages:

```bash
python3 -m pip install -r requirements.txt
```

Launch the application:

```bash
python3 -m streamlit run app.py
```

Open the local address displayed in the terminal, usually `http://localhost:8501`.

## 6. Testing and Visualizations

The prototype has been used to test:

- Fixed versus performance-informed question allocation
- Response and decision logging
- Question selection across multiple rounds
- Descriptive analysis of accuracy by tense and practice round

Demonstration visualizations include an allocation comparison chart and a practice accuracy comparison chart.

## 7. Research Scope and Limitations

**This project demonstrates a functioning adaptive practice mechanism, not evidence that adaptive practice improves learning outcomes.**

The current demonstration does not establish causal effects on learning. Practice accuracy is influenced by item characteristics, question exposure, and the number of opportunities allocated to each tense.

A future evaluation would require randomized assignment, appropriate baseline assessment, common outcome measures, and potentially immediate and delayed posttests.

## 8. Data Privacy

The public repository excludes individual practice records, decision logs, and other private research data.

Only synthetic or appropriately de-identified demonstration materials should be used for public presentation.

## 9. Project Status

**Functional prototype — demonstration and testing stage.**

The project illustrates the translation of a learning-sciences research question into an operational practice allocation system.
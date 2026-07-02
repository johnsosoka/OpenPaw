"""The 39 seed reasoning modules for Self-Discover.

Verbatim from Zhou et al. 2024, "Self-Discover: Large Language Models
Self-Compose Reasoning Structures" (arXiv:2402.03620), Table 2 — adopted
there from Fernando et al. 2023 (Promptbreeder).

Note: the catid/self-discover reference implementation comments out modules
3, 12, 15, and 38 as noise-reduction pragmatics. All 39 ship here verbatim;
the SELECT stage is expected to do the filtering.
"""

SEED_REASONING_MODULES: tuple[str, ...] = (
    "1. How could I devise an experiment to help solve that problem?",
    "2. Make a list of ideas for solving this problem, and apply them one by one to the problem "
    "to see if any progress can be made.",
    "3. How could I measure progress on this problem?",
    "4. How can I simplify the problem so that it is easier to solve?",
    "5. What are the key assumptions underlying this problem?",
    "6. What are the potential risks and drawbacks of each solution?",
    "7. What are the alternative perspectives or viewpoints on this problem?",
    "8. What are the long-term implications of this problem and its solutions?",
    "9. How can I break down this problem into smaller, more manageable parts?",
    "10. Critical Thinking: analyze the problem from different perspectives, question assumptions, "
    "and evaluate the evidence or information available. Focus on logical reasoning, "
    "evidence-based decision-making, and identifying potential biases or flaws in thinking.",
    "11. Try creative thinking: generate innovative and out-of-the-box ideas to solve the problem. "
    "Explore unconventional solutions, thinking beyond traditional boundaries, encouraging "
    "imagination and originality.",
    "12. Seek input and collaboration from others to solve the problem. Emphasize teamwork, open "
    "communication, and leveraging diverse perspectives and expertise of a group.",
    "13. Use systems thinking: consider the problem as part of a larger system; identify underlying "
    "causes, feedback loops, and interdependencies; develop holistic solutions.",
    "14. Use Risk Analysis: evaluate potential risks, uncertainties, and tradeoffs of different "
    "solutions; assess likelihood of success or failure.",
    "15. Use Reflective Thinking: step back, introspect, examine personal biases, assumptions, and "
    "mental models that may influence problem-solving.",
    "16. What is the core issue or problem that needs to be addressed?",
    "17. What are the underlying causes or factors contributing to the problem?",
    "18. Are there any potential solutions or strategies that have been tried before? If yes, what "
    "were the outcomes and lessons learned?",
    "19. What are the potential obstacles or challenges that might arise in solving this problem?",
    "20. Are there any relevant data or information that can provide insights into the problem? If "
    "yes, what data sources are available, and how can they be analyzed?",
    "21. Are there any stakeholders or individuals who are directly affected by the problem? What "
    "are their perspectives and needs?",
    "22. What resources (financial, human, technological, etc.) are needed to tackle the problem "
    "effectively?",
    "23. How can progress or success in solving the problem be measured or evaluated?",
    "24. What indicators or metrics can be used?",
    "25. Is the problem a technical or practical one that requires a specific expertise or skill "
    "set? Or is it more of a conceptual or theoretical problem?",
    "26. Does the problem involve a physical constraint, such as limited resources, infrastructure, "
    "or space?",
    "27. Is the problem related to human behavior, such as a social, cultural, or psychological "
    "issue?",
    "28. Does the problem involve decision-making or planning under uncertainty or with competing "
    "objectives?",
    "29. Is the problem an analytical one that requires data analysis, modeling, or optimization "
    "techniques?",
    "30. Is the problem a design challenge that requires creative solutions and innovation?",
    "31. Does the problem require addressing systemic or structural issues rather than just "
    "individual instances?",
    "32. Is the problem time-sensitive or urgent, requiring immediate attention and action?",
    "33. What kinds of solution typically are produced for this kind of problem specification?",
    "34. Given the problem specification and the current best solution, have a guess about other "
    "possible solutions.",
    "35. Let's imagine the current best solution is totally wrong; what other ways are there to "
    "think about the problem specification?",
    "36. What is the best way to modify this current best solution, given what you know about "
    "these kinds of problem specification?",
    "37. Ignoring the current best solution, create an entirely new solution to the problem.",
    "38. Let's think step by step.",
    "39. Let's make a step by step plan and implement it with good notation and explanation.",
)

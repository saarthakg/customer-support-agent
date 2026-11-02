# Assignment

## A big thank you for your time and interest

- We look forward to welcoming you onsite! This is a short pre-work assignment designed to get you familiar with the kind of work you’d be doing at Sierra.
- We appreciate the time you’ll invest in preparing, and are excited to collaborate with you in person.
- We believe one of the best ways to demonstrate your abilities is to showcase how you would apply them in a simulated customer environment.
- The goal of this exercise is to give you a practical, self-contained problem to work through – and then build an extension of your code together during your onsite interview.

## Some tips for this exercise

- Be creative! The prompt intentionally gives you space to experiment.
- We value craftsmanship, so please pay close attention to the details.
- Don’t spend too much time on this project. We are trying to assess your approach to building agents, not how much free time you have. We don’t expect candidates to spend more than 2-3 hours on this project.
- No UI is expected. You’re welcome to demo your work directly from your terminal.
- You’ll be sharing your work in your onsite at Sierra, so think through how you communicate your ideas and decisions.
- We are your partner and are mutually invested in your success. If you’d like to send questions to the team ahead of time, please take advantage and do so!

---

# Agent Chat Loop: Brief

## Assignment

Use the provided OpenAI API key to write an agent chat loop that enables a user to input a message and receive a text response generated from OpenAI.

Your completed take home should include support for the agent chat loop with the following features:

1. Order Status and Tracking
2. Product Recommendations
3. Early Risers Promotion

During your onsite, you’ll walk us through your implementation in a 20-minute discussion with our team, before building on top of your existing solution live. Be prepared to speak to specific design decisions you made or challenges you encountered during this exercise.

**OpenAI API Key:** `<redacted>`

- Note: Your API Key is only eligible to be used to access gpt-4.1-mini. If you have any issues, please contact us.

## Tooling

You’re welcome (and encouraged) to use code copilots or productivity tools like Cursor, GitHub Copilot, or Claude to assist with your development. Please also feel encouraged to use tool-calling in your agent building exercise.

However, please do not use agent-specific frameworks or orchestration libraries (e.g. OpenAI Agents SDK, AutoGen, agent templates). We’re interested in seeing how you structure an agent from scratch.

## Background

This exercise simulates the early steps in building a Sierra Agent: interpreting a customer request, experimenting with prompt engineering, and structuring agent logic. It gives us insight into how you approach agent design, tradeoffs, and extensibility.

## What We’re Evaluating

We want to understand how your decision making translates to code. We understand this will be a limited sample - we’ll be paying particular attention to the following:

1. **Craft and Code Quality:** Is your code well-structured and easy to follow? Is it easy to extend to additional features or requirements?
2. **Use of AI:** Does the solution demonstrate an understanding of how to integrate LLMs into an application?
3. **Conversation Design:** Does the agent behave correctly with the correct tone?
4. **Communication:** Are decisions and trade-offs clearly articulated?

## Customer Profile: Sierra Outfitters

Sierra Outfitters is an emerging retailer competing with Patagonia, Cotopaxi, and REI. Their CEO left a high-profile job as a leader at HubSpot to pursue her dreams of leading a retail brand. They are completely new to generative AI, and are excited to see its capabilities. Additionally, they are preparing for peak seasonal traffic in which they see significant increases in inbounds and product issues.

## Brand Guidance

Sierra Outfitters wants their agent to make frequent references to the outdoors. Think mountain emojis, enthusiastic phrases like “Onward into the unknown!” and more. You should incorporate this guidance in your agent output.

## Requirements

- **Order Status and Tracking:** After asking the customer’s email and order number, provide information about the order’s status and a tracking link.
  - Use “Appendix A: CustomerOrders.json” as a static dataset
  - Assume the tracking link is: `https://tools.usps.com/go/TrackConfirmAction?tLabels={trackingNumber}`
- **Product Recommendations:** Answer customer questions based off of product catalogue found in Appendix B.
  - Use “Appendix B: ProductCatalog.json” as a static dataset
- **Early Risers Promotion:** Sierra Outfitters offers a 10% discount code to users during the hours of 8:00 - 10:00 AM in Pacific Time. If a customer explicitly requests an Early Risers Promotion during the valid time period, generate a unique discount code for that user.

**Submission:** Please send your completed take-home in a .zip file via the link below at least 24 hours in advance of your onsite.

---

## Submission

Files

Upload File(s)
or drag and drop here

Notes

Submit Assignment

Powered by

Privacy PolicySecurityVulnerability Disclosure
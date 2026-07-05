import { Effect, Schema } from "effect"
import * as Tool from "./tool"
import { Question } from "../question"
import DESCRIPTION from "./question.txt"

export const Parameters = Schema.Struct({
  questions: Schema.mutable(Schema.Array(Question.Prompt)).annotate({ description: "Questions to ask" }),
})

type Metadata = {
  answers: ReadonlyArray<Question.Answer>
}

// Generate auto-answers for all questions when ARGUS_AUTO_ANSWER is set.
// Each question gets the configured value as its answer. This allows
// headless/autonomous mode to bypass the question tool without deadlocking.
function autoAnswer(questions: Array<{ question: string }>): string[][] {
  const defaultAnswer = process.env.ARGUS_AUTO_ANSWER ?? ""
  if (!defaultAnswer) return []
  return questions.map(() => [defaultAnswer])
}

export const QuestionTool = Tool.define<typeof Parameters, Metadata, Question.Service>(
  "question",
  Effect.gen(function* () {
    const question = yield* Question.Service

    return {
      description: DESCRIPTION,
      parameters: Parameters,
      execute: (params: Schema.Schema.Type<typeof Parameters>, ctx: Tool.Context<Metadata>) =>
        Effect.gen(function* () {
          // ARGUS_AUTO_ANSWER bypass: auto-answer without waiting for stdin
          const autoAnswers = autoAnswer(params.questions)
          if (autoAnswers.length > 0) {
            const formatted = params.questions
              .map((q, i) => `"${q.question}"="${autoAnswers[i]?.length ? autoAnswers[i].join(", ") : "Unanswered"}"`)
              .join(", ")
            return {
              title: `Auto-answered ${params.questions.length} question${params.questions.length > 1 ? "s" : ""} (ARGUS_AUTO_ANSWER)`,
              output: `Auto-answered by ARGUS_AUTO_ANSWER: ${formatted}. Continue with these default answers.`,
              metadata: {
                answers: autoAnswers,
              },
            }
          }

          const answers = yield* question.ask({
            sessionID: ctx.sessionID,
            questions: params.questions,
            tool: ctx.callID ? { messageID: ctx.messageID, callID: ctx.callID } : undefined,
          })

          const formatted = params.questions
            .map((q, i) => `"${q.question}"="${answers[i]?.length ? answers[i].join(", ") : "Unanswered"}"`)
            .join(", ")

          return {
            title: `Asked ${params.questions.length} question${params.questions.length > 1 ? "s" : ""}`,
            output: `User has answered your questions: ${formatted}. You can now continue with the user's answers in mind.`,
            metadata: {
              answers,
            },
          }
        }).pipe(Effect.orDie),
    }
  }),
)

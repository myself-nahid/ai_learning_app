import logging
from sqlalchemy import text
from sqlalchemy.future import select
from app.db.session import SessionLocal, engine
from app.db.models import LearningPath, Lesson, QuizSet, QuizQuestion, NewsArticle


logger = logging.getLogger(__name__)


async def ensure_news_article_columns():
    """Ensure the news_articles table has publisher and original_url columns."""
    logger.info("Ensuring news_articles publisher/original_url columns exist.")
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS publisher VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS original_url VARCHAR"
        ))
    logger.info("news_articles schema check complete.")


async def seed_learning_data(db):
    path_check = await db.execute(select(LearningPath))
    if path_check.scalars().first():
        logger.info("Learning data already exists in database. Skipping seed.")
        return

    logger.info("Seeding initial Learning Paths & Lessons...")

    # ── Path 1: Generative AI Fundamentals ──────────────────────────────────
    path1 = LearningPath(
        title="Generative AI Fundamentals",
        description="Learn how AI creates text, images, audio, and other content.",
        level="Beginner",
        total_lessons=6,
        total_minutes=30,
        image_url="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=300&auto=format&fit=crop"
    )
    db.add(path1)
    await db.flush()

    les1 = Lesson(
        path_id=path1.id,
        sequence_order=1,
        title="What Is Generative AI?",
        description="Learn what generative AI means and how it differs from traditional software.",
        estimated_minutes=4,
        cards_data=[
            {
                "type": "intro",
                "heading": "Welcome to Generative AI",
                "text": "Generative AI is a type of artificial intelligence that can create new content — text, images, audio, code, and more — by learning patterns from vast amounts of data.",
                "imageUrl": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=400&auto=format&fit=crop"
            },
            {
                "type": "comparison",
                "heading": "Traditional AI vs Generative AI",
                "text": "Traditional AI classifies or predicts. Generative AI creates brand-new content.",
                "comparisonData": {
                    "traditionalTitle": "Traditional AI",
                    "traditionalBullets": ["Classifies spam emails", "Detects fraudulent transactions", "Predicts stock prices"],
                    "aiTitle": "Generative AI",
                    "aiBullets": ["Writes original emails", "Generates realistic images", "Composes music and code"]
                }
            },
            {
                "type": "list",
                "heading": "What Can Generative AI Create?",
                "text": "Generative AI powers tools across almost every creative domain.",
                "listData": [
                    {"icon": "📝", "text": "Articles, summaries & reports"},
                    {"icon": "🎨", "text": "Images, designs & illustrations"},
                    {"icon": "🎵", "text": "Music, audio & voice"},
                    {"icon": "💻", "text": "Code & software"},
                    {"icon": "🎬", "text": "Videos & animations"}
                ]
            },
            {
                "type": "steps",
                "heading": "How Generative AI Learns",
                "text": "Training a generative model works in three stages.",
                "stepItems": [
                    "Collect a massive dataset of examples (text, images, etc.)",
                    "Feed the data through a neural network repeatedly",
                    "Adjust model weights to minimize prediction errors",
                    "Repeat until the model generates high-quality content"
                ]
            },
            {
                "type": "quiz",
                "heading": "Quick Check",
                "content": {
                    "question": "What makes generative AI different from traditional AI?",
                    "options": [
                        "It can only classify images",
                        "It creates new original content",
                        "It always needs internet access",
                        "It is slower than traditional AI"
                    ],
                    "correct_answer": "It creates new original content"
                }
            }
        ]
    )

    les2 = Lesson(
        path_id=path1.id,
        sequence_order=2,
        title="How AI Models Learn",
        description="Understand training data, patterns, and model predictions.",
        estimated_minutes=5,
        cards_data=[
            {
                "type": "intro",
                "heading": "What is a Large Language Model?",
                "text": "A large language model, or LLM, is an AI system trained to understand and generate human language by learning from billions of text examples.",
                "imageUrl": "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?q=80&w=400&auto=format&fit=crop"
            },
            {
                "type": "example",
                "heading": "Think of an LLM as a pattern predictor",
                "text": "It reads the words that came before and predicts which word is most likely to come next — billions of times per second.",
                "exampleData": {
                    "promptPrefix": "The sky is very",
                    "predictionWord": "blue",
                    "noteText": "The model predicts the most likely next word based on learned patterns."
                }
            },
            {
                "type": "steps",
                "heading": "How an LLM Generates Text",
                "text": "Language models generate responses through a step-by-step token prediction process.",
                "stepItems": [
                    "It receives your prompt",
                    "It breaks the prompt into tokens",
                    "It analyzes learned patterns",
                    "It predicts the next token",
                    "It repeats until the response is complete"
                ]
            },
            {
                "type": "comparison",
                "heading": "Traditional Search vs. Language Model",
                "text": "Traditional software retrieves index links, whereas language models synthesize answers.",
                "comparisonData": {
                    "traditionalTitle": "Traditional Search",
                    "traditionalBullets": ["Finds existing web pages", "Returns links to sources"],
                    "aiTitle": "Language Model",
                    "aiBullets": ["Generates new responses", "Synthesizes information", "Explains in plain language"]
                }
            },
            {
                "type": "list",
                "heading": "Where Are LLMs Used?",
                "text": "Language models power modern digital applications across diverse industries.",
                "listData": [
                    {"icon": "💬", "text": "AI chat assistants"},
                    {"icon": "✍️", "text": "Writing & summarization"},
                    {"icon": "💻", "text": "Code generation"},
                    {"icon": "🌐", "text": "Language translation"},
                    {"icon": "📞", "text": "Customer support"}
                ]
            },
            {
                "type": "quiz",
                "heading": "Knowledge Check",
                "content": {
                    "question": "Which statement best describes an LLM?",
                    "options": [
                        "A database that stores every answer",
                        "A model that predicts language patterns",
                        "A search engine that only finds websites",
                        "A robot that understands everything"
                    ],
                    "correct_answer": "A model that predicts language patterns"
                }
            }
        ]
    )

    les3 = Lesson(
        path_id=path1.id,
        sequence_order=3,
        title="Understanding Large Language Models",
        description="Learn how LLMs process text and generate human-like responses.",
        estimated_minutes=5,
        cards_data=[
            {
                "type": "intro",
                "heading": "Inside an LLM",
                "text": "Large Language Models are neural networks with billions of parameters, trained on massive text datasets to understand and generate language."
            },
            {
                "type": "example",
                "heading": "What Are Tokens?",
                "text": "LLMs don't process whole words — they process tokens, which are word fragments.",
                "exampleData": {
                    "promptPrefix": "\"Unbelievable\" →",
                    "predictionWord": "4 tokens",
                    "noteText": "\"Un\" + \"believ\" + \"able\" + \".\" — shorter words are usually one token each."
                }
            },
            {
                "type": "quiz",
                "heading": "Knowledge Check",
                "content": {
                    "question": "What does 'LLM' stand for?",
                    "options": [
                        "Low Latency Machine",
                        "Large Logic Model",
                        "Large Language Model",
                        "Linear Learning Method"
                    ],
                    "correct_answer": "Large Language Model"
                }
            }
        ]
    )

    db.add_all([les1, les2, les3])

    # ── Path 2: Prompt Engineering Mastery ─────────────────────────────────
    path2 = LearningPath(
        title="Prompt Engineering Mastery",
        description="Write clearer instructions and get better results from AI tools.",
        level="Beginner",
        total_lessons=5,
        total_minutes=25,
        image_url="https://images.unsplash.com/photo-1542744094-3a31727202b3?q=80&w=300&auto=format&fit=crop"
    )
    db.add(path2)
    await db.flush()

    les_p2_1 = Lesson(
        path_id=path2.id,
        sequence_order=1,
        title="Prompt Engineering Basics",
        description="Write clearer instructions and get better results from AI tools.",
        estimated_minutes=5,
        cards_data=[
            {
                "type": "intro",
                "heading": "What is Prompt Engineering?",
                "text": "Prompt engineering is the practice of designing and refining the inputs you give to AI systems to get the best possible outputs."
            },
            {
                "type": "steps",
                "heading": "The Anatomy of a Great Prompt",
                "text": "Every powerful prompt has four key elements working together.",
                "stepItems": [
                    "Role — Tell the AI who it should be",
                    "Task — State what you want it to do",
                    "Context — Provide necessary background",
                    "Format — Specify how you want the answer"
                ]
            },
            {
                "type": "quiz",
                "heading": "Knowledge Check",
                "content": {
                    "question": "What is the primary goal of prompt engineering?",
                    "options": [
                        "Writing computer code",
                        "Crafting inputs to get optimal AI outputs",
                        "Designing neural network architectures",
                        "Managing database connections"
                    ],
                    "correct_answer": "Crafting inputs to get optimal AI outputs"
                }
            }
        ]
    )
    db.add(les_p2_1)

    # ── Path 3: Machine Learning Foundations ──────────────────────────────
    path3 = LearningPath(
        title="Machine Learning Foundations",
        description="Understand algorithms, models, and real-world AI architecture.",
        level="Intermediate",
        total_lessons=4,
        total_minutes=20,
        image_url="https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?q=80&w=300&auto=format&fit=crop"
    )
    db.add(path3)
    await db.flush()

    les_p3_1 = Lesson(
        path_id=path3.id,
        sequence_order=1,
        title="Supervised vs Unsupervised Learning",
        description="Learn how machines identify patterns with or without labeled data.",
        estimated_minutes=5,
        cards_data=[
            {
                "type": "intro",
                "heading": "Types of Machine Learning",
                "text": "Machine learning algorithms learn from data to make predictions or uncover hidden structures."
            },
            {
                "type": "quiz",
                "heading": "Knowledge Check",
                "content": {
                    "question": "Supervised learning relies on which type of data?",
                    "options": [
                        "Unlabeled data",
                        "Labeled input-output pairs",
                        "Random noise",
                        "No data at all"
                    ],
                    "correct_answer": "Labeled input-output pairs"
                }
            }
        ]
    )
    db.add(les_p3_1)
    await db.commit()
    logger.info("Successfully seeded Learning Paths & Lessons!")


async def seed_quiz_data(db):
    quiz_check = await db.execute(select(QuizSet))
    if quiz_check.scalars().first():
        logger.info("Quiz data already exists in database. Skipping seed.")
        return

    logger.info("Seeding initial Quiz Sets & Questions...")

    # Set 1: Robotics Fundamentals
    q_set1 = QuizSet(
        category="Robotics",
        title="Robotics Fundamentals",
        description="Test your understanding of robots, automation, and intelligent machines.",
        level="Beginner",
        total_questions=2,
        estimated_minutes=2,
        xp_reward=10
    )
    db.add(q_set1)
    await db.flush()

    q1 = QuizQuestion(
        quiz_set_id=q_set1.id,
        question_text="Who mentioned that the meeting was postponed to Friday?",
        options={"A": "Anna", "B": "Marek", "C": "Zofia", "D": "None of them"},
        correct_option_key="C"
    )
    q2 = QuizQuestion(
        quiz_set_id=q_set1.id,
        question_text="What is the primary function of an LLM?",
        options={"A": "Storing images", "B": "Predicting text patterns", "C": "Driving cars", "D": "None of the above"},
        correct_option_key="B"
    )
    db.add_all([q1, q2])

    # Set 2: Generative AI Concepts
    q_set2 = QuizSet(
        category="Generative AI",
        title="Generative AI Essentials",
        description="Test your knowledge on LLMs, tokens, and generative capabilities.",
        level="Beginner",
        total_questions=2,
        estimated_minutes=3,
        xp_reward=15
    )
    db.add(q_set2)
    await db.flush()

    q3 = QuizQuestion(
        quiz_set_id=q_set2.id,
        question_text="What does 'RAG' stand for in AI architecture?",
        options={
            "A": "Random Access Generation",
            "B": "Retrieval-Augmented Generation",
            "C": "Rapid Artificial Intelligence",
            "D": "Recursive Agent Graph"
        },
        correct_option_key="B"
    )
    q4 = QuizQuestion(
        quiz_set_id=q_set2.id,
        question_text="What is the context window of an LLM?",
        options={
            "A": "The browser window size",
            "B": "The maximum text the model can process at once",
            "C": "The GPU memory limit",
            "D": "The user interface layout"
        },
        correct_option_key="B"
    )
    db.add_all([q3, q4])

    # Set 3: Sports Analytics
    q_set3 = QuizSet(
        category="Sports",
        title="AI in Sports Analytics",
        description="Test your understanding of player tracking, performance prediction, and computer vision in sports.",
        level="Beginner",
        total_questions=2,
        estimated_minutes=3,
        xp_reward=15
    )
    db.add(q_set3)
    await db.flush()

    q5 = QuizQuestion(
        quiz_set_id=q_set3.id,
        question_text="How do computer vision models track ball trajectory during live broadcasts?",
        options={"A": "GPS sensors", "B": "High-frame-rate multi-camera tracking", "C": "Manual keying", "D": "Radio frequency tags"},
        correct_option_key="B"
    )
    q6 = QuizQuestion(
        quiz_set_id=q_set3.id,
        question_text="What metric is calculated by AI models to evaluate shot quality in soccer?",
        options={"A": "Expected Goals (xG)", "B": "Pass Completion Index", "C": "Sprint Rate", "D": "Tactical Ratio"},
        correct_option_key="A"
    )
    db.add_all([q5, q6])

    # Set 4: Politics & Governance
    q_set4 = QuizSet(
        category="Politics",
        title="AI Governance & Policy",
        description="Explore global AI regulations, ethical frameworks, and election security.",
        level="Intermediate",
        total_questions=2,
        estimated_minutes=3,
        xp_reward=20
    )
    db.add(q_set4)
    await db.flush()

    q7 = QuizQuestion(
        quiz_set_id=q_set4.id,
        question_text="Which major regulatory framework classifies AI systems by risk tiers?",
        options={"A": "EU AI Act", "B": "Digital Millennium Act", "C": "ISO 9001", "D": "NIST AI Standard"},
        correct_option_key="A"
    )
    q8 = QuizQuestion(
        quiz_set_id=q_set4.id,
        question_text="What technique is used to verify authentic media against deepfakes in political campaigns?",
        options={"A": "Digital Watermarking & Provenance", "B": "Bitrate Compression", "C": "Color Balance", "D": "Encryption Keys"},
        correct_option_key="A"
    )
    db.add_all([q7, q8])

    await db.commit()
    logger.info("Successfully seeded Quiz Sets & Questions!")


async def init_db():
    await ensure_news_article_columns()
    async with SessionLocal() as db:
        await seed_learning_data(db)
        await seed_quiz_data(db)
    logger.info("Database initialization check complete.")



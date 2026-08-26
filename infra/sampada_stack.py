"""Phase 2: the Bedrock Knowledge Base and the S3 bucket it reads from.
Phase 5 adds the Next.js app's own IAM role, now that we know it's an
Amplify Hosting SSR "compute role" (trust: amplify.amazonaws.com), verified
against AWS's docs rather than assumed. Phase 6 adds the scheduled Lambda
that keeps the archive current.
"""
import aws_cdk as cdk
from aws_cdk import Duration
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.aws_lambda_python_alpha import PythonFunction
from cdklabs.generative_ai_cdk_constructs import bedrock
from constructs import Construct

# Where Phase 1 writes the browse-page index (see ingest/build_index.py).
# Deliberately outside processed/ so the KB's data source (scoped to
# processed/) never tries to embed it as an article.
BROWSE_INDEX_KEY = "index/issues.json"


class SampadaStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # An explicit bucket_name context value (`-c bucket_name=...`) is
        # only honored if you've already confirmed that name is globally
        # free. Left unset, CDK generates a unique physical name for you --
        # "sampada-archive" from the spec is illustrative, not reserved.
        bucket_name = self.node.try_get_context("bucket_name")

        self.archive_bucket = s3.Bucket(
            self,
            "ArchiveBucket",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            # 70 years of institutional archive: never let `cdk destroy`
            # silently take this out.
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # embeddings_model + no vector_store/vector_index given -> the
        # construct provisions a new OpenSearch Serverless collection and
        # vector index for us, matching the spec's "Bedrock's default
        # managed option, no separate provisioning".
        self.knowledge_base = bedrock.VectorKnowledgeBase(
            self,
            "SampadaKnowledgeBase",
            name="sampada-archive-kb",
            embeddings_model=bedrock.BedrockFoundationModel.TITAN_EMBED_TEXT_V2_1024,
            instruction=(
                "Use this knowledge base to answer questions about Sampada, "
                "MCCIA's monthly industrial magazine. It contains individual "
                "articles from 70+ years of issues. Every chunk is tagged "
                "with the issue's month/year and the article's title -- use "
                "that to cite sources and to answer issue-scoped questions."
            ),
        )
        # OpenSearch Serverless collections created by this construct don't
        # expose a removal policy directly today; if that changes, pin it to
        # RETAIN here too so a stack teardown can't take the vector index
        # (and therefore the archive's searchability) with it by accident.

        self.data_source = self.knowledge_base.add_s3_data_source(
            bucket=self.archive_bucket,
            data_source_name="sampada-processed-articles",
            description=(
                "One text file per article under processed/<year>/<month>/, "
                "each with a .metadata.json sidecar carrying issue_month, "
                "issue_year, article_title, source_url, content_type."
            ),
            # raw/ holds whole-issue PDFs -- only processed/ (one file per
            # article) should ever be embedded.
            inclusion_prefixes=["processed/"],
            # Spec: "each file is already one article, so use default
            # fixed-size chunking within each file (roughly 300 tokens)".
            chunking_strategy=bedrock.ChunkingStrategy.fixed_size(
                max_tokens=300,
                overlap_percentage=20,
            ),
        )

        # The Next.js app's own role (spec's Deployment section): "read-only
        # bedrock:RetrieveAndGenerate and bedrock:Retrieve on the knowledge
        # base, nothing broader." The one addition -- read access to a single
        # S3 key for the browse page's index -- was a call made with you:
        # Bedrock's retrieve APIs are semantic search, not built for an
        # exhaustive chronological listing, so the browse page needs a real
        # index somewhere, and this is the narrowest way to expose one.
        #
        # This is an Amplify Hosting "SSR compute role", not a generic IAM
        # role -- confirmed against AWS's docs. It must trust
        # amplify.amazonaws.com, and it isn't attached to an app by CDK here:
        # that happens once a real Amplify App resource exists for this repo
        # (Deployment step, needs a live git remote we don't have yet). This
        # role's ARN is what you'll paste into that app's Compute role
        # setting (console, or `compute_role_arn` on CfnApp/CfnBranch).
        self.app_role = iam.Role(
            self,
            "SampadaAppRole",
            assumed_by=iam.ServicePrincipal("amplify.amazonaws.com"),
            description=(
                "Amplify Hosting SSR compute role for the Sampada Next.js app: "
                "Bedrock KB retrieve/generate, plus read-only access to the "
                "browse page's index.json."
            ),
        )
        self.knowledge_base.grant_retrieve(self.app_role)
        self.knowledge_base.grant_retrieve_and_generate(self.app_role)
        self.archive_bucket.grant_read(self.app_role, BROWSE_INDEX_KEY)

        # Phase 6: keep the archive current. A weekly check is plenty for a
        # monthly magazine -- "never falls behind" doesn't require hourly
        # polling, and this keeps Lambda/Bedrock costs negligible. Change
        # the Schedule below if you want a different cadence.
        #
        # Holds the Google Drive service account key. Value is a placeholder
        # -- update it after deploy with:
        #   aws secretsmanager put-secret-value --secret-id <arn> \
        #     --secret-string file://drive-service-account.json
        self.drive_credentials_secret = secretsmanager.Secret(
            self,
            "DriveCredentialsSecret",
            description="Google service account JSON key for Sampada's Drive sync (Phase 6).",
        )

        self.keep_current_fn = PythonFunction(
            self,
            "KeepCurrentFunction",
            entry="../ingest",
            index="lambda_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            timeout=Duration.minutes(10),
            memory_size=1024,
            description="Phase 6: pulls new Drive PDFs, processes them, and checks mcciapunesampada.com for issues we don't have yet.",
            environment={
                "AWS_REGION": self.region,
                "S3_BUCKET": self.archive_bucket.bucket_name,
                "BEDROCK_KNOWLEDGE_BASE_ID": self.knowledge_base.knowledge_base_id,
                "BEDROCK_DATA_SOURCE_ID": self.data_source.data_source_id,
                "GOOGLE_DRIVE_CREDENTIALS_SECRET_ARN": self.drive_credentials_secret.secret_arn,
                # These three still need real values (Drive folder ID +
                # Bedrock inference profile ARN) -- fill in after deploy via
                # `aws lambda update-function-configuration`, same as any
                # other CHANGE-ME in this project.
                "GOOGLE_DRIVE_ROOT_FOLDER_ID": "CHANGE-ME",
                "BEDROCK_ARTICLE_SPLIT_MODEL_ID": "CHANGE-ME",
                "GOOGLE_SERVICE_ACCOUNT_FILE": "/tmp/drive-service-account.json",
                "LOCAL_STAGING_DIR": "/tmp/staging/raw",
                "LOCAL_PROCESSED_DIR": "/tmp/staging/processed",
                "LOCAL_INDEX_PATH": "/tmp/staging/index/issues.json",
                "STATE_MANIFEST": "/tmp/staging/processed_manifest.json",
                "MANUAL_REVIEW_LOG": "/tmp/staging/manual_review.csv",
            },
        )

        self.archive_bucket.grant_read_write(self.keep_current_fn)
        self.drive_credentials_secret.grant_read(self.keep_current_fn)
        self.knowledge_base.grant_retrieve_and_generate(self.keep_current_fn)
        self.keep_current_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob", "bedrock:GetIngestionJob"],
                resources=[self.knowledge_base.knowledge_base_arn],
            )
        )
        # Claude via a "global." inference profile can route to any of
        # several commercial regions (see sampada/README.md) -- IAM has to
        # allow invoking the profile AND the underlying foundation models it
        # might route to. This is broad on purpose until a real deploy
        # confirms exactly which regions/models to narrow it to.
        self.keep_current_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                ],
            )
        )

        events.Rule(
            self,
            "KeepCurrentSchedule",
            description="Weekly check for new Sampada issues (Phase 6).",
            schedule=events.Schedule.rate(Duration.days(7)),
            targets=[targets.LambdaFunction(self.keep_current_fn)],
        )

        cdk.CfnOutput(self, "ArchiveBucketName", value=self.archive_bucket.bucket_name)
        cdk.CfnOutput(self, "KnowledgeBaseId", value=self.knowledge_base.knowledge_base_id)
        cdk.CfnOutput(self, "KnowledgeBaseArn", value=self.knowledge_base.knowledge_base_arn)
        cdk.CfnOutput(self, "DataSourceId", value=self.data_source.data_source_id)
        cdk.CfnOutput(self, "AppRoleArn", value=self.app_role.role_arn)
        cdk.CfnOutput(self, "BrowseIndexS3Uri", value=f"s3://{self.archive_bucket.bucket_name}/{BROWSE_INDEX_KEY}")
        cdk.CfnOutput(self, "DriveCredentialsSecretArn", value=self.drive_credentials_secret.secret_arn)
        cdk.CfnOutput(self, "KeepCurrentFunctionName", value=self.keep_current_fn.function_name)

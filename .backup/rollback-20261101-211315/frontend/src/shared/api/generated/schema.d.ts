export interface paths {
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 健康检查 */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 会话列表（搜索 + 分页，置顶优先） */
        get: operations["list_threads_api_v1_threads_get"];
        put?: never;
        /** 新建会话 */
        post: operations["create_thread_api_v1_threads_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 会话详情 */
        get: operations["get_thread_api_v1_threads__thread_id__get"];
        put?: never;
        post?: never;
        /** 软删会话（列表不再返回） */
        delete: operations["delete_thread_api_v1_threads__thread_id__delete"];
        options?: never;
        head?: never;
        /** 重命名 / 置顶 */
        patch: operations["update_thread_api_v1_threads__thread_id__patch"];
        trace?: never;
    };
    "/api/v1/threads/reorder": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 重排会话顺序（左栏拖动排序）
         * @description 按传入顺序重写 sort_index。整份列表一起传，重编号后顺序才是确定的。
         */
        post: operations["reorder_threads_api_v1_threads_reorder_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/bulk-delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 批量软删会话（左栏「批量清理」）
         * @description 一次请求删一批：列表是分页拉的，逐个 DELETE 要发 N 次、失败半途还会留下半成品状态。
         */
        post: operations["bulk_delete_threads_api_v1_threads_bulk_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}/files": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 会话素材列表 */
        get: operations["list_files_api_v1_threads__thread_id__files_get"];
        put?: never;
        /** 上传素材（单文件 file / 多文件 files） */
        post: operations["upload_files_api_v1_threads__thread_id__files_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/files/{file_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 删除素材（软删 + 移入 data/trash） */
        delete: operations["delete_file_api_v1_files__file_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}/runs/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 发起任务（SSE） */
        post: operations["stream_run_api_v1_threads__thread_id__runs_stream_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 运行列表（可按会话/状态过滤） */
        get: operations["list_runs_api_v1_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 会话运行列表 */
        get: operations["list_thread_runs_api_v1_threads__thread_id__runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 运行详情 */
        get: operations["get_run_api_v1_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 取消运行（中断任务并推送 run.cancelled，重复调用幂等） */
        post: operations["cancel_run_api_v1_runs__run_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 重试运行（同会话同任务消息新建 run，SSE 返回） */
        post: operations["retry_run_api_v1_runs__run_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 运行事件回放（JSON） */
        get: operations["list_run_events_api_v1_runs__run_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/events/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 运行事件回放（SSE，支持 Last-Event-ID 断线续传） */
        get: operations["stream_run_events_api_v1_runs__run_id__events_stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}/approvals/{approval_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 提交审批决议 */
        post: operations["decide_approval_api_v1_threads__thread_id__approvals__approval_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 产物列表（分页/筛选） */
        get: operations["list_artifacts_api_v1_artifacts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/trash": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 回收站列表（已软删的产物，可恢复 / 彻底删除） */
        get: operations["list_trash_api_v1_artifacts_trash_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 从回收站恢复（文件挪回原目录） */
        post: operations["restore_artifact_api_v1_artifacts__artifact_id__restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/purge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 彻底删除（清掉回收站文件与记录，不可恢复） */
        delete: operations["purge_artifact_api_v1_artifacts__artifact_id__purge_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/open": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 用系统默认程序打开（装了 WPS 即用 WPS） */
        post: operations["open_artifact_api_v1_artifacts__artifact_id__open_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/batch-delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 批量软删产物（部分成功语义，逐条返回结果） */
        post: operations["batch_delete_artifacts_api_v1_artifacts_batch_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 产物元数据 */
        get: operations["get_artifact_api_v1_artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        /** 软删产物（文件移入 data/trash，下载/预览返回 404） */
        delete: operations["delete_artifact_api_v1_artifacts__artifact_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 产物下载（软删后 404）；inline=1 时浏览器内联打开（PDF 预览用） */
        get: operations["download_artifact_api_v1_artifacts__artifact_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 产物预览（HTML 片段） */
        get: operations["preview_artifact_api_v1_artifacts__artifact_id__preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 基于原 run 的任务消息重新生成（SSE 返回新 run） */
        post: operations["regenerate_artifact_api_v1_artifacts__artifact_id__regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 读取设置（含来源 db/env/default 与密钥引用） */
        get: operations["get_settings_api_v1_settings_get"];
        /** 更新设置（保存即热生效） */
        put: operations["update_settings_api_v1_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 模型供应商列表（不含明文 Key，只返回引用与探测状态） */
        get: operations["list_models_api_v1_models_get"];
        put?: never;
        /** 新增/更新模型登记（api_key_ref 只允许 env:NAME） */
        post: operations["upsert_model_api_v1_models_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/models/{model_id}/key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 保存供应商 Key（明文只落本地 .env，响应仅回显掩码） */
        put: operations["save_model_key_api_v1_models__model_id__key_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/models/{model_id}/balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查供应商账户余额（对账用：确认本地账单花的是这个账号） */
        get: operations["model_balance_api_v1_models__model_id__balance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/models/{model_id}/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 真实探测模型（失败返回脱敏原因，不泄露 Key） */
        post: operations["test_model_api_v1_models__model_id__test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 模板列表（内置 + 自定义） */
        get: operations["list_templates_api_v1_templates_get"];
        put?: never;
        /** 新增自定义模板（存 settings 表） */
        post: operations["create_template_api_v1_templates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 删除自定义模板（内置模板不可删） */
        delete: operations["delete_template_api_v1_templates__template_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/templates/{template_id}/render": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 用模板生成 DOCX 产物（同步返回产物元数据） */
        post: operations["render_template_api_v1_templates__template_id__render_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 已加载技能与启用状态 */
        get: operations["list_skills_api_v1_skills_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 技能库：可一键添加的内置技能（未添加的不进提示词） */
        get: operations["list_skill_catalog_api_v1_skills_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/catalog/{skill_id}/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 从技能库添加技能（复制到 app/skills 并默认启用） */
        post: operations["install_skill_from_catalog_api_v1_skills_catalog__skill_id__install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/{skill_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 删除技能（目录挪进 app/skills/.trash，可人工捞回） */
        delete: operations["delete_skill_api_v1_skills__skill_id__delete"];
        options?: never;
        head?: never;
        /** 启用/停用技能（立即影响运行时提示词与模板 enabled 状态） */
        patch: operations["patch_skill_api_v1_skills__skill_id__patch"];
        trace?: never;
    };
    "/api/v1/skills/draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 让当前模型把一句话需求写成一张技能便签（没模型时返回本地骨架）
         * @description 「先让模型写一版，再让人改」比「从空白模板开始」容易得多。
         *
         *     产物是一份合法的 SKILL.md，前端拿走后仍然走 /skills/import 落盘，
         *     所以这里不写任何文件，也不改任何运行期状态。
         */
        post: operations["draft_skill_api_v1_skills_draft_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 导入技能（上传一个 SKILL.md，导入后立即出现在技能列表里） */
        post: operations["import_skill_api_v1_skills_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/prompt-packs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 内置提示词包（按需求自动匹配注入本轮 system prompt） */
        get: operations["list_prompt_packs_api_v1_prompt_packs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 项目列表（含文件数 / 最近修改 / 目录是否还在） */
        get: operations["list_projects_api_v1_projects_get"];
        put?: never;
        /** 把本地文件夹添加为项目 */
        post: operations["create_project_api_v1_projects_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 移除项目（只取消登记，不删文件） */
        delete: operations["delete_project_api_v1_projects__project_id__delete"];
        options?: never;
        head?: never;
        /** 重命名项目 / 置顶 */
        patch: operations["update_project_api_v1_projects__project_id__patch"];
        trace?: never;
    };
    "/api/v1/projects/{project_id}/files": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 项目内的文档列表（docx/pdf/xlsx/md/txt/pptx，按修改时间倒序） */
        get: operations["list_project_files_api_v1_projects__project_id__files_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}/reveal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 在系统文件管理器中打开项目文件夹 */
        post: operations["reveal_project_api_v1_projects__project_id__reveal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/storage/browse": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 浏览本机文件夹（目录选择器用，只列子目录不列文件） */
        get: operations["browse_storage_api_v1_storage_browse_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/storage/browse/mkdir": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 在指定目录下新建文件夹 */
        post: operations["make_storage_dir_api_v1_storage_browse_mkdir_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/storage/paths": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 本机存储目录（绝对路径 / 是否存在 / 文件数） */
        get: operations["get_storage_paths_api_v1_storage_paths_get"];
        /** 修改存储目录（绝对路径；传空表示恢复默认） */
        put: operations["set_storage_paths_api_v1_storage_paths_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/storage/reveal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 在系统文件管理器中打开存储目录 */
        post: operations["reveal_storage_api_v1_storage_reveal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/desktop/package": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 桌面端安装包：可交付状态 + 上次保存的位置 */
        get: operations["get_desktop_package_api_v1_desktop_package_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/desktop/package/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 把桌面端安装包保存到本机（默认系统下载目录） */
        post: operations["download_desktop_package_api_v1_desktop_package_download_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/desktop/package/reveal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 在文件管理器中定位已保存的安装包 */
        post: operations["reveal_desktop_package_api_v1_desktop_package_reveal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/desktop/package/open": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 打开已保存的安装包（重新安装 / 再次启动桌面端） */
        post: operations["open_desktop_package_api_v1_desktop_package_open_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 已注册工具（含 JSON Schema） */
        get: operations["list_tools_api_v1_tools_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/subagents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 已注册子智能体（1 实现 + 2 占位） */
        get: operations["list_subagents_api_v1_subagents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/threads/{thread_id}/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 会话审计 */
        get: operations["audit_thread_api_v1_threads__thread_id__audit_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usage/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 用量汇总（按日/供应商/模型聚合，支持 7d/30d） */
        get: operations["usage_summary_api_v1_usage_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usage/provider": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 官方控制台用量（对账参考；需先填 userToken）
         * @description 拉官方控制台的真实用量。
         *
         *     官方这个词这里要打个引号理解：接口是平台网页端自用的私有接口，未对外承诺
         *     稳定，鉴权用浏览器登录态而不是 API Key。所以失败一律返回 200 + available=false
         *     + error，让前端安静地退回本地账本，而不是弹一个没人看得懂的 5xx。
         */
        get: operations["provider_usage_api_v1_usage_provider_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usage/provider/token": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 设置官方用量 token（仅存进程内存，重启即失效） */
        put: operations["set_provider_token_api_v1_usage_provider_token_put"];
        post?: never;
        /** 清除官方用量 token */
        delete: operations["clear_provider_token_api_v1_usage_provider_token_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usage/balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 账户余额（走 API Key 的公开接口） */
        get: operations["account_balance_api_v1_usage_balance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 审计导出（json/csv，返回文件下载） */
        get: operations["export_audit_api_v1_audit_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 提交意见反馈（本机存档 + 生成邮件） */
        post: operations["submit_feedback_api_v1_feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/prompts/enhance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 增强提示词：把一句话需求补成可执行的指令（没模型时按本地规则补全）
         * @description 空文本在入口就拒掉：把空白喂给模型只会换回一句「请描述你的需求」。
         */
        post: operations["enhance_api_v1_prompts_enhance_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ApprovalDecisionOut */
        ApprovalDecisionOut: {
            /** Trace Id */
            trace_id: string;
            /** Approval Id */
            approval_id: string;
            /** Decision */
            decision: string;
            /** Decided At */
            decided_at: string;
            /** Resumed */
            resumed: boolean;
        };
        /** ApprovalOut */
        ApprovalOut: {
            /** Approval Id */
            approval_id: string;
            /** Thread Id */
            thread_id: string;
            /** Run Id */
            run_id: string | null;
            /** Tool */
            tool: string;
            /** Risk */
            risk: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /** Decision */
            decision?: string | null;
            /** Comment */
            comment?: string | null;
            /** Created At */
            created_at: string;
            /** Decided At */
            decided_at?: string | null;
            /**
             * Policy Version
             * @default v1
             */
            policy_version: string;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
        };
        /** ApprovalRequestIn */
        ApprovalRequestIn: {
            /**
             * Decision
             * @description approved | rejected
             */
            decision: string;
            /** Comment */
            comment?: string | null;
        };
        /** ArtifactBatchDeleteIn */
        ArtifactBatchDeleteIn: {
            /**
             * Artifact Ids
             * @description 待软删的产物 ID 列表（单次上限 200，重复 ID 自动去重）
             */
            artifact_ids?: string[];
        };
        /** ArtifactBatchDeleteItem */
        ArtifactBatchDeleteItem: {
            /** Artifact Id */
            artifact_id: string;
            /** Deleted */
            deleted: boolean;
            /**
             * Message
             * @description 失败原因（成功时为空）
             * @default
             */
            message: string;
        };
        /** ArtifactBatchDeleteOut */
        ArtifactBatchDeleteOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Requested
             * @description 去重后的请求数量
             */
            requested: number;
            /**
             * Deleted
             * @description 实际软删成功数量
             */
            deleted: number;
            /** Failed */
            failed?: components["schemas"]["ArtifactBatchDeleteItem"][];
            /**
             * Trashed
             * @description 移入回收站的文件路径
             */
            trashed?: string[];
        };
        /** ArtifactEnvelope */
        ArtifactEnvelope: {
            /** Artifact Id */
            artifact_id: string;
            /**
             * Type
             * @description docx | pdf | txt | xlsx | upload
             */
            type: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /**
             * Sha256
             * @default
             */
            sha256: string;
            /**
             * Content Type
             * @default
             */
            content_type: string;
            /** Created At */
            created_at: string;
            /** Thread Id */
            thread_id: string;
            /** Run Id */
            run_id?: string | null;
            /** Download Url */
            download_url: string;
            /** Preview Url */
            preview_url: string;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
            /**
             * Sources
             * @description 生成该产物的素材文件名；同一天多份产物靠它区分是哪一份
             */
            sources?: string[];
            /**
             * Has Preview File
             * @default false
             */
            has_preview_file: boolean;
            /**
             * Has Text
             * @default false
             */
            has_text: boolean;
            /** Trace Id */
            trace_id: string;
        };
        /** ArtifactListOut */
        ArtifactListOut: {
            /** Trace Id */
            trace_id: string;
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactOut"][];
            /**
             * Total
             * @default 0
             */
            total: number;
            /**
             * Page
             * @default 1
             */
            page: number;
            /**
             * Page Size
             * @default 20
             */
            page_size: number;
        };
        /** ArtifactOut */
        ArtifactOut: {
            /** Artifact Id */
            artifact_id: string;
            /**
             * Type
             * @description docx | pdf | txt | xlsx | upload
             */
            type: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /**
             * Sha256
             * @default
             */
            sha256: string;
            /**
             * Content Type
             * @default
             */
            content_type: string;
            /** Created At */
            created_at: string;
            /** Thread Id */
            thread_id: string;
            /** Run Id */
            run_id?: string | null;
            /** Download Url */
            download_url: string;
            /** Preview Url */
            preview_url: string;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
            /**
             * Sources
             * @description 生成该产物的素材文件名；同一天多份产物靠它区分是哪一份
             */
            sources?: string[];
            /**
             * Has Preview File
             * @default false
             */
            has_preview_file: boolean;
            /**
             * Has Text
             * @default false
             */
            has_text: boolean;
        };
        /**
         * ArtifactTrashItem
         * @description 回收站条目：多一个删除时间与「文件是否可挪回」标记。
         */
        ArtifactTrashItem: {
            /** Artifact Id */
            artifact_id: string;
            /**
             * Type
             * @description docx | pdf | txt | xlsx | upload
             */
            type: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /**
             * Sha256
             * @default
             */
            sha256: string;
            /**
             * Content Type
             * @default
             */
            content_type: string;
            /** Created At */
            created_at: string;
            /** Thread Id */
            thread_id: string;
            /** Run Id */
            run_id?: string | null;
            /** Download Url */
            download_url: string;
            /** Preview Url */
            preview_url: string;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
            /**
             * Sources
             * @description 生成该产物的素材文件名；同一天多份产物靠它区分是哪一份
             */
            sources?: string[];
            /**
             * Has Preview File
             * @default false
             */
            has_preview_file: boolean;
            /**
             * Has Text
             * @default false
             */
            has_text: boolean;
            /**
             * Deleted At
             * @description 软删时间
             */
            deleted_at?: string | null;
            /**
             * Restorable
             * @description 文件仍在回收站目录，可恢复
             * @default true
             */
            restorable: boolean;
        };
        /** ArtifactTrashListOut */
        ArtifactTrashListOut: {
            /** Trace Id */
            trace_id: string;
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactTrashItem"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** AuditOut */
        AuditOut: {
            /** Trace Id */
            trace_id: string;
            /** Thread Id */
            thread_id: string;
            /**
             * Thread Title
             * @default
             */
            thread_title: string;
            /** Runs */
            runs: components["schemas"]["AuditRunOut"][];
            /** Approvals */
            approvals: components["schemas"]["ApprovalOut"][];
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactOut"][];
        };
        /** AuditRunOut */
        AuditRunOut: {
            /** Run Id */
            run_id: string;
            /** Started At */
            started_at: string;
            /** Finished At */
            finished_at?: string | null;
            /** Status */
            status: string;
            /** Mode */
            mode: string;
            /** Engine */
            engine: string;
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
            /** Elapsed Ms */
            elapsed_ms: number;
            /** Error Code */
            error_code?: string | null;
            /**
             * Degraded
             * @default false
             */
            degraded: boolean;
            /**
             * Request Ids
             * @description 最近几次模型调用的供应商请求 id（用于与供应商控制台对账）
             */
            request_ids?: string[];
            /**
             * Calls
             * @description 本轮外部模型调用次数
             * @default 0
             */
            calls: number;
            /**
             * Verified Calls
             * @description 带回执 id 的调用次数；小于 calls 说明有调用没拿到回执
             * @default 0
             */
            verified_calls: number;
            /**
             * Provider Model
             * @description 供应商回执里的实际模型名，可能与配置的 model 不同（官方侧会做重路由）
             */
            provider_model?: string | null;
            /** Approvals */
            approvals?: {
                [key: string]: unknown;
            }[];
            /** Artifacts */
            artifacts?: {
                [key: string]: unknown;
            }[];
        };
        /** Body_import_skill_api_v1_skills_import_post */
        Body_import_skill_api_v1_skills_import_post: {
            /** File */
            file: string;
        };
        /** Body_upload_files_api_v1_threads__thread_id__files_post */
        Body_upload_files_api_v1_threads__thread_id__files_post: {
            /** File */
            file?: string | null;
            /** Files */
            files?: string[] | null;
        };
        /** CatalogSkillOut */
        CatalogSkillOut: {
            /** Name */
            name: string;
            /**
             * Title
             * @description 展示名（frontmatter 的 title，缺省回落 name）
             * @default
             */
            title: string;
            /** Description */
            description: string;
            /** Triggers */
            triggers?: string[];
            /** Enabled */
            enabled: boolean;
            /**
             * Category
             * @description 技能分类，技能页的分类筛选用它
             * @default
             */
            category: string;
            /**
             * Icon
             * @description 图标键（doc/sheet/minutes/retro/shield/book），前端映射成图标
             * @default
             */
            icon: string;
            /**
             * Badge
             * @description 角标文案（必备精选 / 新功能推荐），空串表示没有
             * @default
             */
            badge: string;
            /**
             * Content Chars
             * @default 0
             */
            content_chars: number;
            /**
             * Slug
             * @description 技能目录名，安装时按它复制目录
             */
            slug: string;
            /**
             * Installed
             * @description 是否已添加到 app/skills（已添加的不再重复安装）
             */
            installed: boolean;
        };
        /** DeleteOut */
        DeleteOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Deleted
             * @default true
             */
            deleted: boolean;
            /** Artifact Id */
            artifact_id: string;
            /**
             * Trashed
             * @description 移入回收站的文件路径
             */
            trashed?: string[];
        };
        /** DesktopActionOut */
        DesktopActionOut: {
            /** Trace Id */
            trace_id: string;
            /** Ok */
            ok: boolean;
            /** Path */
            path?: string | null;
            /**
             * Exists
             * @description 动作前文件是否还在
             * @default false
             */
            exists: boolean;
            /** Error */
            error?: string | null;
        };
        /** DesktopDownloadIn */
        DesktopDownloadIn: {
            /**
             * Target Dir
             * @description 保存目录的绝对路径；空表示系统下载目录
             */
            target_dir?: string | null;
        };
        /** DesktopDownloadOut */
        DesktopDownloadOut: {
            /** Trace Id */
            trace_id: string;
            /** Ok */
            ok: boolean;
            /**
             * Path
             * @description 成功时的绝对路径
             */
            path?: string | null;
            saved?: components["schemas"]["DesktopSavedOut"] | null;
            /** Error */
            error?: string | null;
        };
        /** DesktopPackageOut */
        DesktopPackageOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Available
             * @description 服务端有没有可交付的安装包
             */
            available: boolean;
            /**
             * Filename
             * @description 交付时的文件名
             */
            filename: string;
            /**
             * Size
             * @description 安装包字节数；没有则为 0
             */
            size: number;
            /**
             * Platform
             * @description windows / macos / linux
             */
            platform: string;
            /**
             * Default Dir
             * @description 不指定目录时的默认保存位置（系统下载目录）
             */
            default_dir: string;
            /** @description 上次成功保存的记录 */
            saved?: components["schemas"]["DesktopSavedOut"] | null;
        };
        /**
         * DesktopSavedOut
         * @description 一次成功保存的记录（读取时现算文件是否还在）。
         */
        DesktopSavedOut: {
            /**
             * Path
             * @description 保存完成时的绝对路径
             */
            path: string;
            /**
             * Filename
             * @description 文件名
             */
            filename: string;
            /**
             * Size
             * @description 字节数
             */
            size: number;
            /**
             * Saved At
             * @description 保存时间（ISO 8601）
             */
            saved_at: string;
            /**
             * Exists
             * @description 此刻文件是否还在；被删 / 被移走为 false
             */
            exists: boolean;
            /**
             * Dir Exists
             * @description 所在目录是否还在
             */
            dir_exists: boolean;
            /**
             * Error
             * @description exists=false 时的原因说明
             */
            error?: string | null;
        };
        /** ErrorDetail */
        ErrorDetail: {
            /**
             * Code
             * @description 错误码，见 core/errors.py ErrorCode 枚举
             */
            code: string;
            /**
             * Message
             * @description 人类可读错误信息
             */
            message: string;
            /**
             * Details
             * @description 结构化补充信息（可选）
             */
            details?: unknown | null;
        };
        /** ErrorResponse */
        ErrorResponse: {
            /**
             * Trace Id
             * @description 请求追踪 ID
             */
            trace_id: string;
            error: components["schemas"]["ErrorDetail"];
        };
        /** FeedbackIn */
        FeedbackIn: {
            /**
             * Kind
             * @description 反馈类型：bug | idea | other
             * @default idea
             */
            kind: string;
            /**
             * Message
             * @description 反馈内容（上限 1500 字，超出的部分会被截断）
             */
            message: string;
            /**
             * Contact
             * @description 可选：邮箱或微信，便于回访
             * @default
             */
            contact: string;
            /**
             * Include Diagnostics
             * @description 是否附带版本/引擎/窗口形态等环境信息（便于定位问题）
             * @default true
             */
            include_diagnostics: boolean;
            /**
             * Client
             * @description 前端上报的窗口形态/系统/屏幕等展示信息，只用于邮件正文
             */
            client?: {
                [key: string]: string;
            };
        };
        /** FeedbackOut */
        FeedbackOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Id
             * @description 反馈编号（本机存档的文件里也有）
             */
            id: string;
            /** Kind */
            kind: string;
            /**
             * Saved
             * @description 是否已写入本机存档
             */
            saved: boolean;
            /**
             * Saved Path
             * @description 本机存档文件路径
             */
            saved_path: string;
            /**
             * Target
             * @description 开发者收件邮箱；空串表示还没配置
             */
            target: string;
            /**
             * Subject
             * @description 邮件标题
             */
            subject: string;
            /**
             * Body
             * @description 邮件正文（可直接复制粘贴）
             */
            body: string;
            /**
             * Mailto
             * @description mailto 链接；target 为空时也是空串
             */
            mailto: string;
            /**
             * Truncated
             * @description 正文是否因过长被截断
             * @default false
             */
            truncated: boolean;
        };
        /** FileListOut */
        FileListOut: {
            /** Trace Id */
            trace_id: string;
            /** Thread Id */
            thread_id: string;
            /** Files */
            files: components["schemas"]["FileOut"][];
        };
        /** FileOut */
        FileOut: {
            /** File Id */
            file_id: string;
            /** Artifact Id */
            artifact_id: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /** Type */
            type: string;
            /** Ext */
            ext: string;
            /** Chars */
            chars: number;
            /** Parsed */
            parsed: boolean;
            /**
             * Text Preview
             * @default
             */
            text_preview: string;
            /** Created At */
            created_at: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthOut */
        HealthOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Status
             * @description 服务状态，固定 ok
             */
            status: string;
            /**
             * Version
             * @description 后端版本
             */
            version: string;
            /**
             * Git Sha
             * @description 当前提交 SHA（进程启动时载入的版本）
             */
            git_sha: string;
            /**
             * Git Sha Live
             * @description 仓库当前 HEAD；与 git_sha 不同说明后端进程比代码旧，需要重启
             * @default
             */
            git_sha_live: string;
            /**
             * Mode
             * @description mock | real
             */
            mode: string;
            /**
             * Provider
             * @description 当前模型供应商
             */
            provider: string;
            /**
             * Model
             * @description 当前模型名
             */
            model: string;
            /**
             * Degraded
             * @description 真实模型探测失败后是否已降级
             */
            degraded: boolean;
            /**
             * Degraded Reason
             * @description 降级原因（人话，便于判断是 Key、网络还是模型名的问题）
             * @default
             */
            degraded_reason: string;
            /** Mock */
            mock: boolean;
            /**
             * Tools
             * @description 已注册工具数量
             */
            tools: number;
            /**
             * Subagents
             * @description 子智能体数量
             */
            subagents: number;
            /**
             * Skills
             * @description 已加载技能名
             */
            skills: string[];
            /** Prompt Version */
            prompt_version: string;
            /**
             * Engine
             * @description 配置的引擎：mock | real | deepagents
             * @default real
             */
            engine: string;
            /**
             * Engine Effective
             * @description 实际生效引擎（无 Key/引擎未实现时自动降级）
             * @default mock
             */
            engine_effective: string;
            /**
             * Engine Supported
             * @description 配置的引擎是否已有实现（deepagents 为 planned）
             * @default true
             */
            engine_supported: boolean;
            /**
             * Engine Reason
             * @description 实际生效引擎与配置不一致时的人话原因（开关/缺 Key/探测失败）
             * @default
             */
            engine_reason: string;
            /** Engines */
            engines?: string[];
            /** Approval Tools */
            approval_tools?: string[];
        };
        /** MessageOut */
        MessageOut: {
            /** Message Id */
            message_id: string;
            /** Thread Id */
            thread_id: string;
            /** Role */
            role: string;
            /** Content */
            content: string;
            /** Run Id */
            run_id?: string | null;
            /** Created At */
            created_at: string;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
        };
        /** ModelBalanceOut */
        ModelBalanceOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Supported
             * @description 该供应商是否提供余额查询接口（DeepSeek 支持）
             */
            supported: boolean;
            /** Provider */
            provider: string;
            /**
             * Currency
             * @default CNY
             */
            currency: string;
            /**
             * Total Balance
             * @description 账户总余额
             */
            total_balance?: number | null;
            /**
             * Granted Balance
             * @description 赠送余额
             */
            granted_balance?: number | null;
            /**
             * Topped Up Balance
             * @description 充值余额
             */
            topped_up_balance?: number | null;
            /** Checked At */
            checked_at: string;
            /**
             * Reason
             * @description 不支持/查询失败的原因（脱敏）
             */
            reason?: string | null;
        };
        /** ModelCreateIn */
        ModelCreateIn: {
            /**
             * Id
             * @description 更新已有登记时传入
             */
            id?: string | null;
            /**
             * Provider
             * @description deepseek | qwen | glm | openai | 自定义
             */
            provider: string;
            /** Base Url */
            base_url?: string | null;
            /** Model */
            model?: string | null;
            /**
             * Api Key Ref
             * @description 只允许 env:NAME 形式；禁止明文 Key
             */
            api_key_ref?: string | null;
            /**
             * Priority
             * @default 100
             */
            priority: number;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** ModelEnvelope */
        ModelEnvelope: {
            /** Id */
            id: string;
            /** Provider */
            provider: string;
            /** Base Url */
            base_url: string;
            /** Model */
            model: string;
            /**
             * Api Key Ref
             * @description Key 引用，如 env:DEEPSEEK_API_KEY（不返回明文）
             */
            api_key_ref: string;
            /**
             * Configured
             * @description 对应环境变量中的 Key 是否存在
             */
            configured: boolean;
            /** Enabled */
            enabled: boolean;
            /** Priority */
            priority: number;
            /**
             * Builtin
             * @description 是否来自环境变量内置配置
             * @default false
             */
            builtin: boolean;
            /**
             * Last Probe
             * @description 最近一次探测结果
             */
            last_probe?: {
                [key: string]: unknown;
            } | null;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
            /** Trace Id */
            trace_id: string;
        };
        /** ModelKeyIn */
        ModelKeyIn: {
            /**
             * Api Key
             * @description 供应商开放平台获取的 Key 明文；只落本地 .env，不回显
             */
            api_key: string;
            /**
             * Env Name
             * @description 可选：环境变量名（缺省按供应商约定，如 DEEPSEEK_API_KEY）
             */
            env_name?: string | null;
        };
        /** ModelKeyOut */
        ModelKeyOut: {
            /** Trace Id */
            trace_id: string;
            /** Provider */
            provider: string;
            /** Api Key Ref */
            api_key_ref: string;
            /** Configured */
            configured: boolean;
            /**
             * Masked
             * @description 掩码展示，如 sk-****abcd
             */
            masked: string;
            /**
             * Persisted
             * @description 是否已写入本地 .env（只读文件系统时为 false）
             */
            persisted: boolean;
        };
        /** ModelListOut */
        ModelListOut: {
            /** Trace Id */
            trace_id: string;
            /** Models */
            models: components["schemas"]["ModelOut"][];
        };
        /** ModelOut */
        ModelOut: {
            /** Id */
            id: string;
            /** Provider */
            provider: string;
            /** Base Url */
            base_url: string;
            /** Model */
            model: string;
            /**
             * Api Key Ref
             * @description Key 引用，如 env:DEEPSEEK_API_KEY（不返回明文）
             */
            api_key_ref: string;
            /**
             * Configured
             * @description 对应环境变量中的 Key 是否存在
             */
            configured: boolean;
            /** Enabled */
            enabled: boolean;
            /** Priority */
            priority: number;
            /**
             * Builtin
             * @description 是否来自环境变量内置配置
             * @default false
             */
            builtin: boolean;
            /**
             * Last Probe
             * @description 最近一次探测结果
             */
            last_probe?: {
                [key: string]: unknown;
            } | null;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
        };
        /** ModelTestOut */
        ModelTestOut: {
            /** Trace Id */
            trace_id: string;
            /** Ok */
            ok: boolean;
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /** Api Key Ref */
            api_key_ref: string;
            /** Latency Ms */
            latency_ms: number;
            /** Returned Model */
            returned_model?: string | null;
            /**
             * Reason
             * @description 失败原因（脱敏，不含 Key）
             */
            reason?: string | null;
        };
        /** ProjectCreateIn */
        ProjectCreateIn: {
            /**
             * Path
             * @description 文件夹绝对路径
             */
            path: string;
            /**
             * Name
             * @description 项目名，缺省用文件夹名
             */
            name?: string | null;
        };
        /** ProjectUpdateIn */
        ProjectUpdateIn: {
            /** Name */
            name?: string | null;
            /** Pinned */
            pinned?: boolean | null;
        };
        /**
         * PromptEnhanceIn
         * @description 输入框右侧「增强提示词」的入参：就取当前输入框里的原文。
         */
        PromptEnhanceIn: {
            /**
             * Text
             * @description 当前输入框里的需求原文（上限 4000 字）
             */
            text: string;
            /**
             * Output Format
             * @description 期望的产物格式（docx | pdf | xlsx | txt），只作为改写提示，不改变产物
             */
            output_format?: string | null;
        };
        /** PromptEnhanceOut */
        PromptEnhanceOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Text
             * @description 增强后的提示词（直接替换输入框内容）
             */
            text: string;
            /**
             * Source
             * @description 来源：model（模型改写）| rules（本地规则补全）
             */
            source: string;
            /**
             * Model
             * @description 实际使用的模型名；rules 时为空串
             * @default
             */
            model: string;
            /**
             * Note
             * @description 给用户的一句说明（本地补全时解释为什么）
             * @default
             */
            note: string;
        };
        /** ProviderBalanceOut */
        ProviderBalanceOut: {
            /**
             * Available
             * @default false
             */
            available: boolean;
            /** Currency */
            currency?: string | null;
            /** Total */
            total?: string | null;
            /** Granted */
            granted?: string | null;
            /** Topped Up */
            topped_up?: string | null;
        };
        /** ProviderTokenIn */
        ProviderTokenIn: {
            /**
             * Provider
             * @default deepseek
             */
            provider: string;
            /**
             * Token
             * @description 浏览器 localStorage.userToken 的值（可粘贴完整 JSON）；只存进程内存，不落盘
             */
            token: string;
        };
        /** ProviderTokenOut */
        ProviderTokenOut: {
            /** Provider */
            provider: string;
            /** Has Token */
            has_token: boolean;
            /**
             * Token Preview
             * @default
             */
            token_preview: string;
            error?: components["schemas"]["ProviderUsageErrorOut"] | null;
        };
        /** ProviderUsageDayOut */
        ProviderUsageDayOut: {
            /** Date */
            date: string;
            /**
             * Requests
             * @default 0
             */
            requests: number;
            /**
             * Tokens
             * @default 0
             */
            tokens: number;
            /**
             * Cost Cny
             * @default 0
             */
            cost_cny: number;
        };
        /** ProviderUsageErrorOut */
        ProviderUsageErrorOut: {
            /**
             * Code
             * @description NO_TOKEN | TOKEN_EXPIRED | TOKEN_EMPTY | TOKEN_TOO_SHORT | NETWORK
             */
            code: string;
            /** Message */
            message: string;
        };
        /**
         * ProviderUsageOut
         * @description 官方控制台用量：和本地账本并排显示，差额就是「本应用之外的消耗」。
         */
        ProviderUsageOut: {
            /** Trace Id */
            trace_id: string;
            /** Provider */
            provider: string;
            /**
             * Available
             * @description false 表示没取到（未填 token / token 过期 / 网络不通）
             */
            available: boolean;
            /**
             * Has Token
             * @default false
             */
            has_token: boolean;
            /**
             * Token Preview
             * @default
             */
            token_preview: string;
            /** Month */
            month?: string | null;
            /**
             * Source
             * @description 数据来源地址，便于核对
             */
            source?: string | null;
            /**
             * Requests
             * @default 0
             */
            requests: number;
            /**
             * Tokens
             * @default 0
             */
            tokens: number;
            /**
             * Cost Cny
             * @default 0
             */
            cost_cny: number;
            /**
             * Cache Hit Tokens
             * @default 0
             */
            cache_hit_tokens: number;
            /**
             * Cache Miss Tokens
             * @default 0
             */
            cache_miss_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /** Days */
            days?: components["schemas"]["ProviderUsageDayOut"][];
            balance?: components["schemas"]["ProviderBalanceOut"] | null;
            /** Fetched At */
            fetched_at?: string | null;
            /**
             * Note
             * @default
             */
            note: string;
            /**
             * Unparsed
             * @description 官方响应结构变了，没能解析出用量
             * @default false
             */
            unparsed: boolean;
            /**
             * Raw
             * @description 未解析时附带的原始响应
             */
            raw?: {
                [key: string]: unknown;
            } | null;
            error?: components["schemas"]["ProviderUsageErrorOut"] | null;
        };
        /** RunCancelOut */
        RunCancelOut: {
            /** Trace Id */
            trace_id: string;
            /** Run Id */
            run_id: string;
            /**
             * Cancelled
             * @description 本次是否真正中断了运行
             */
            cancelled: boolean;
            /**
             * Status
             * @description 取消后（或原本）的运行状态
             */
            status: string;
            /**
             * Idempotent
             * @description 重复取消时为 true
             */
            idempotent: boolean;
        };
        /** RunEnvelope */
        RunEnvelope: {
            /** Run Id */
            run_id: string;
            /** Thread Id */
            thread_id: string;
            /**
             * Status
             * @description running | completed | rejected | failed | cancelled
             */
            status: string;
            /** Mode */
            mode: string;
            /** Engine */
            engine: string;
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
            /** Started At */
            started_at: string;
            /** Finished At */
            finished_at?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
            /** Trace Id */
            trace_id: string;
        };
        /** RunEventOut */
        RunEventOut: {
            /** Seq */
            seq: number;
            /** Event */
            event: string;
            /** Data */
            data: {
                [key: string]: unknown;
            };
            /** Created At */
            created_at: string;
        };
        /** RunEventsOut */
        RunEventsOut: {
            /** Trace Id */
            trace_id: string;
            /** Run Id */
            run_id: string;
            /** Events */
            events: components["schemas"]["RunEventOut"][];
        };
        /** RunListOut */
        RunListOut: {
            /** Trace Id */
            trace_id: string;
            /** Runs */
            runs: components["schemas"]["RunOut"][];
            /**
             * Total
             * @default 0
             */
            total: number;
            /**
             * Page
             * @default 1
             */
            page: number;
            /**
             * Page Size
             * @default 20
             */
            page_size: number;
        };
        /** RunOut */
        RunOut: {
            /** Run Id */
            run_id: string;
            /** Thread Id */
            thread_id: string;
            /**
             * Status
             * @description running | completed | rejected | failed | cancelled
             */
            status: string;
            /** Mode */
            mode: string;
            /** Engine */
            engine: string;
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
            /** Started At */
            started_at: string;
            /** Finished At */
            finished_at?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Extra */
            extra?: {
                [key: string]: unknown;
            };
        };
        /** RunRequestIn */
        RunRequestIn: {
            /**
             * Message
             * @default
             */
            message: string;
            /**
             * Mode
             * @description mock | real；缺省按配置
             */
            mode?: string | null;
            /**
             * Output Format
             * @description 产物格式：docx | pdf | xlsx | txt；缺省时与首个上传素材同格式，无素材时 docx
             */
            output_format?: string | null;
            /**
             * Run Id
             * @description 断线续传：配合 Last-Event-ID / after 回放该运行事件
             */
            run_id?: string | null;
            /**
             * Project Id
             * @description 左栏选中的项目 ID：本轮把项目里的文档作为素材一起交给 Agent
             */
            project_id?: string | null;
            /**
             * Project Files
             * @description 只带项目里的这些文件（相对路径）；缺省带最近修改的若干文档
             */
            project_files?: string[] | null;
            /**
             * Approval Mode
             * @description 审批策略：always_ask（高风险一律问）| risky（按设置的规则，默认）| all_allow（全权交给 Agent，不再打断）
             */
            approval_mode?: string | null;
            /**
             * Attachment Ids
             * @description 本轮使用的附件 ID（会话内上传的素材）；缺省表示沿用该会话全部素材（兼容旧客户端）
             */
            attachment_ids?: string[] | null;
        };
        /** SettingSecretOut */
        SettingSecretOut: {
            /** Configured */
            configured: boolean;
            /**
             * Ref
             * @description 密钥环境变量引用，如 env:DASHSCOPE_API_KEY
             */
            ref: string;
            /**
             * Via
             * @description 兼容回退来源，如 env:OPENAI_API_KEY
             */
            via?: string | null;
        };
        /** SettingsOut */
        SettingsOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Engine
             * @description 引擎：mock | real | deepagents
             */
            engine: string;
            /**
             * Approval Rules
             * @description 需审批工具列表
             */
            approval_rules: string[];
            /** Mock Mode */
            mock_mode: boolean;
            /** Model Provider */
            model_provider: string;
            /** Model Name */
            model_name: string;
            /** Fallback Chain */
            fallback_chain: string[];
            /** Max Upload Mb */
            max_upload_mb: number;
            /** Model Timeout Seconds */
            model_timeout_seconds: number;
            /** Approval Timeout Seconds */
            approval_timeout_seconds: number;
            /** Feature Flags */
            feature_flags?: {
                [key: string]: unknown;
            };
            /**
             * Sources
             * @description 每个可配置项的来源：db | env | default
             * @example {
             *       "approval_rules": "db",
             *       "model_provider": "env"
             *     }
             */
            sources: {
                [key: string]: string;
            };
            /**
             * Env Hints
             * @description 对应环境变量名
             * @example {
             *       "model_provider": "MODEL_PROVIDER"
             *     }
             */
            env_hints: {
                [key: string]: string;
            };
            /**
             * Secrets
             * @description 模型 Key 只返回引用，不返回明文
             */
            secrets: {
                [key: string]: components["schemas"]["SettingSecretOut"];
            };
            /** Database Url */
            database_url: string;
            /** Upload Dir */
            upload_dir: string;
            /** Artifact Dir */
            artifact_dir: string;
            /** Log Level */
            log_level: string;
            /** Environment */
            environment: string;
        };
        /** SettingsUpdateIn */
        SettingsUpdateIn: {
            /**
             * Engine
             * @description mock | real | deepagents
             */
            engine?: string | null;
            /** Approval Rules */
            approval_rules?: string | string[] | null;
            /** Mock Mode */
            mock_mode?: boolean | null;
            /** Model Provider */
            model_provider?: string | null;
            /** Model Name */
            model_name?: string | null;
            /** Fallback Chain */
            fallback_chain?: string | string[] | null;
            /** Max Upload Mb */
            max_upload_mb?: number | null;
            /** Model Timeout Seconds */
            model_timeout_seconds?: number | null;
            /** Approval Timeout Seconds */
            approval_timeout_seconds?: number | null;
            /** Feature Flags */
            feature_flags?: {
                [key: string]: unknown;
            } | null;
        };
        /** SkillCatalogOut */
        SkillCatalogOut: {
            /** Trace Id */
            trace_id: string;
            /** Skills */
            skills: components["schemas"]["CatalogSkillOut"][];
            /**
             * Categories
             * @description 技能库里出现过的分类，按首见顺序去重
             */
            categories: string[];
        };
        /**
         * SkillDraftIn
         * @description 「让模型帮你写」的输入：一句话说清这张便签要干什么。
         */
        SkillDraftIn: {
            /**
             * Idea
             * @description 用一句大白话说想要的效果，例如「把录音转成会议纪要，只留结论和待办」
             */
            idea: string;
        };
        /** SkillDraftOut */
        SkillDraftOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Markdown
             * @description 完整的 SKILL.md 文本，可直接拿去导入
             */
            markdown: string;
            /**
             * Name
             * @description 技能内部标识（同名会自动加数字后缀）
             */
            name: string;
            /** Title */
            title: string;
            /** Description */
            description: string;
            /** Triggers */
            triggers: string[];
            /**
             * Model
             * @description 生成用的模型；本地骨架时为空串
             * @default
             */
            model: string;
            /**
             * Source
             * @description model = 模型写的；local = 没模型时的本地骨架
             */
            source: string;
            /**
             * Note
             * @description 给用户看的一句说明（要不要改、怎么改）
             * @default
             */
            note: string;
        };
        /** SkillInstallOut */
        SkillInstallOut: {
            /** Trace Id */
            trace_id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            skill?: components["schemas"]["SkillOut"] | null;
        };
        /** SkillListOut */
        SkillListOut: {
            /** Trace Id */
            trace_id: string;
            /** Skills */
            skills: components["schemas"]["SkillOut"][];
            /**
             * Prompt Chars
             * @description 当前运行时提示词长度，启停技能后立即变化
             */
            prompt_chars: number;
        };
        /** SkillOut */
        SkillOut: {
            /** Name */
            name: string;
            /**
             * Title
             * @description 展示名（frontmatter 的 title，缺省回落 name）
             * @default
             */
            title: string;
            /** Description */
            description: string;
            /** Triggers */
            triggers?: string[];
            /** Enabled */
            enabled: boolean;
            /**
             * Category
             * @description 技能分类，技能页的分类筛选用它
             * @default
             */
            category: string;
            /**
             * Icon
             * @description 图标键（doc/sheet/minutes/retro/shield/book），前端映射成图标
             * @default
             */
            icon: string;
            /**
             * Badge
             * @description 角标文案（必备精选 / 新功能推荐），空串表示没有
             * @default
             */
            badge: string;
            /**
             * Content Chars
             * @default 0
             */
            content_chars: number;
        };
        /** SkillPatchIn */
        SkillPatchIn: {
            /** Enabled */
            enabled: boolean;
        };
        /** SkillPatchOut */
        SkillPatchOut: {
            /** Trace Id */
            trace_id: string;
            /** Name */
            name: string;
            /** Enabled */
            enabled: boolean;
            /** Prompt Chars */
            prompt_chars: number;
        };
        /** StorageBrowseMkdirIn */
        StorageBrowseMkdirIn: {
            /**
             * Path
             * @description 在哪个目录下新建
             */
            path: string;
            /**
             * Name
             * @description 新文件夹名（不能含路径分隔符）
             */
            name: string;
        };
        /** StorageRevealIn */
        StorageRevealIn: {
            /**
             * Kind
             * @description uploads | artifacts
             * @enum {string}
             */
            kind: "uploads" | "artifacts";
        };
        /** StorageSetIn */
        StorageSetIn: {
            /**
             * Kind
             * @description uploads | artifacts
             * @enum {string}
             */
            kind: "uploads" | "artifacts";
            /**
             * Path
             * @description 新的绝对路径；传 null / 空字符串表示恢复默认目录
             */
            path?: string | null;
        };
        /** SubagentListOut */
        SubagentListOut: {
            /** Trace Id */
            trace_id: string;
            /** Subagents */
            subagents: components["schemas"]["SubagentOut"][];
        };
        /** SubagentOut */
        SubagentOut: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Tools */
            tools?: string[];
            /** Status */
            status: string;
            /** Step Limit */
            step_limit: number;
        };
        /** TemplateCreateIn */
        TemplateCreateIn: {
            /** Id */
            id?: string | null;
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Sections
             * @description 小节顺序与数据来源映射
             * @example [
             *       {
             *         "heading": "本周进展",
             *         "source": "progress"
             *       }
             *     ]
             */
            sections: components["schemas"]["TemplateSectionOut"][];
        };
        /** TemplateEnvelope */
        TemplateEnvelope: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Builtin
             * @default false
             */
            builtin: boolean;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Sections */
            sections?: components["schemas"]["TemplateSectionOut"][];
            /** Trace Id */
            trace_id: string;
        };
        /** TemplateListOut */
        TemplateListOut: {
            /** Trace Id */
            trace_id: string;
            /** Templates */
            templates: components["schemas"]["TemplateOut"][];
        };
        /** TemplateOut */
        TemplateOut: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Builtin
             * @default false
             */
            builtin: boolean;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Sections */
            sections?: components["schemas"]["TemplateSectionOut"][];
        };
        /** TemplateRenderOut */
        TemplateRenderOut: {
            /** Trace Id */
            trace_id: string;
            /** Run Id */
            run_id: string;
            /** Template */
            template: string;
            artifact: components["schemas"]["ArtifactOut"];
        };
        /** TemplateSectionOut */
        TemplateSectionOut: {
            /** Heading */
            heading: string;
            /**
             * Source
             * @description summary | progress | data | risk | plan
             */
            source: string;
        };
        /** ThreadBulkDeleteIn */
        ThreadBulkDeleteIn: {
            /**
             * Thread Ids
             * @description 要软删的会话 ID（1–200 个；不存在的 ID 忽略，不报错）
             */
            thread_ids: string[];
        };
        /** ThreadBulkDeleteOut */
        ThreadBulkDeleteOut: {
            /**
             * Trace Id
             * @description 请求追踪 ID
             */
            trace_id: string;
            /**
             * Deleted
             * @description 真正被软删的会话数（已删/不存在的 ID 不计）
             */
            deleted: number;
        };
        /** ThreadCreateIn */
        ThreadCreateIn: {
            /**
             * Title
             * @description 会话标题，缺省为『新会话』
             */
            title?: string | null;
        };
        /** ThreadCreateOut */
        ThreadCreateOut: {
            /** Thread Id */
            thread_id: string;
            /** Title */
            title: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /**
             * Pinned
             * @default false
             */
            pinned: boolean;
            /**
             * Message Count
             * @default 0
             */
            message_count: number;
            /**
             * Artifact Count
             * @default 0
             */
            artifact_count: number;
            /** Trace Id */
            trace_id: string;
        };
        /** ThreadDetailEnvelope */
        ThreadDetailEnvelope: {
            /** Thread Id */
            thread_id: string;
            /** Title */
            title: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /**
             * Pinned
             * @default false
             */
            pinned: boolean;
            /**
             * Message Count
             * @default 0
             */
            message_count: number;
            /**
             * Artifact Count
             * @default 0
             */
            artifact_count: number;
            /** Messages */
            messages?: components["schemas"]["MessageOut"][];
            /** Artifacts */
            artifacts?: components["schemas"]["ArtifactOut"][];
            /**
             * Uploads
             * @description 本会话的素材文件
             */
            uploads?: components["schemas"]["FileOut"][];
            /** Trace Id */
            trace_id: string;
        };
        /** ThreadListOut */
        ThreadListOut: {
            /** Trace Id */
            trace_id: string;
            /** Threads */
            threads: components["schemas"]["ThreadOut"][];
            /**
             * Total
             * @description 过滤后总数
             * @default 0
             */
            total: number;
            /**
             * Page
             * @default 1
             */
            page: number;
            /**
             * Page Size
             * @default 20
             */
            page_size: number;
        };
        /** ThreadOut */
        ThreadOut: {
            /** Thread Id */
            thread_id: string;
            /** Title */
            title: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /**
             * Pinned
             * @default false
             */
            pinned: boolean;
            /**
             * Message Count
             * @default 0
             */
            message_count: number;
            /**
             * Artifact Count
             * @default 0
             */
            artifact_count: number;
        };
        /** ThreadReorderIn */
        ThreadReorderIn: {
            /**
             * Thread Ids
             * @description 按新顺序排好的会话 ID（从前往后）；顺序写入 threads.sort_index
             */
            thread_ids: string[];
        };
        /** ThreadReorderOut */
        ThreadReorderOut: {
            /** Trace Id */
            trace_id: string;
            /**
             * Reordered
             * @description 真正写进库的会话条数
             * @default 0
             */
            reordered: number;
        };
        /** ThreadUpdateIn */
        ThreadUpdateIn: {
            /**
             * Title
             * @description 重命名（非空）
             */
            title?: string | null;
            /**
             * Pinned
             * @description 是否置顶
             */
            pinned?: boolean | null;
        };
        /** ToolListOut */
        ToolListOut: {
            /** Trace Id */
            trace_id: string;
            /** Tools */
            tools: components["schemas"]["ToolOut"][];
        };
        /** ToolOut */
        ToolOut: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Risk */
            risk: string;
            /** Schema */
            schema: {
                [key: string]: unknown;
            };
        };
        /** UploadItemOut */
        UploadItemOut: {
            /** File Id */
            file_id: string;
            /** Artifact Id */
            artifact_id: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /**
             * Type
             * @description 扩展名（不含点）
             */
            type: string;
            /** Ext */
            ext: string;
            /**
             * Chars
             * @description 解析后字数
             */
            chars: number;
            /** Parsed */
            parsed: boolean;
            /**
             * Text Preview
             * @description 解析文本前 200 字预览
             * @default
             */
            text_preview: string;
        };
        /**
         * UploadResultOut
         * @description 兼容 v0.1 单文件响应（顶层为第一个文件字段），并追加 files 列表。
         */
        UploadResultOut: {
            /** File Id */
            file_id: string;
            /** Artifact Id */
            artifact_id: string;
            /** Filename */
            filename: string;
            /** Size */
            size: number;
            /**
             * Type
             * @description 扩展名（不含点）
             */
            type: string;
            /** Ext */
            ext: string;
            /**
             * Chars
             * @description 解析后字数
             */
            chars: number;
            /** Parsed */
            parsed: boolean;
            /**
             * Text Preview
             * @description 解析文本前 200 字预览
             * @default
             */
            text_preview: string;
            /** Trace Id */
            trace_id: string;
            /**
             * Files
             * @description 本次上传的全部文件
             */
            files: components["schemas"]["UploadItemOut"][];
        };
        /** UsageDayOut */
        UsageDayOut: {
            /** Date */
            date: string;
            /** Runs */
            runs: number;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
            /** Elapsed Ms */
            elapsed_ms: number;
            /**
             * Calls
             * @description 当天发生的大模型计费请求次数
             * @default 0
             */
            calls: number;
            /**
             * Mock Runs
             * @description 当天本地 mock 运行数（不计费）
             * @default 0
             */
            mock_runs: number;
        };
        /** UsageModelOut */
        UsageModelOut: {
            /** Model */
            model: string;
            /** Runs */
            runs: number;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
        };
        /** UsageOut */
        UsageOut: {
            /** Trace Id */
            trace_id: string;
            /** Thread Id */
            thread_id?: string | null;
            /**
             * Range
             * @description 7d | 30d | today | all
             * @default 7d
             */
            range: string;
            /** Since */
            since?: string | null;
            /** Runs */
            runs: number;
            /**
             * Real Runs
             * @description 真实模型调用运行数（会产生费用）
             * @default 0
             */
            real_runs: number;
            /**
             * Mock Runs
             * @description 本地 mock 运行数（不计费）
             * @default 0
             */
            mock_runs: number;
            /**
             * Api Calls
             * @description 大模型计费请求次数：一次运行内有十余轮工具调用，每轮都是一次独立请求。供应商控制台的「API 请求次数」是这个口径，不是运行数
             * @default 0
             */
            api_calls: number;
            /**
             * Tokens
             * @description 只统计真实调用的 tokens
             */
            tokens: number;
            /**
             * Cost Cny
             * @description 只统计真实调用的成本；按当前价目表重算，mock 不计费
             */
            cost_cny: number;
            /**
             * Cache Hit Tokens
             * @description 输入里命中上下文缓存的 tokens
             * @default 0
             */
            cache_hit_tokens: number;
            /**
             * Cache Miss Tokens
             * @description 输入里未命中缓存的 tokens（按全价计）
             * @default 0
             */
            cache_miss_tokens: number;
            /**
             * Cancelled Runs
             * @description 被取消的运行数（已花费的用量已计入上方合计）
             * @default 0
             */
            cancelled_runs: number;
            /**
             * Cancelled Tokens
             * @description 被取消的运行在中断前已消耗的 tokens
             * @default 0
             */
            cancelled_tokens: number;
            /**
             * Cancelled Cost Cny
             * @description 被取消的运行在中断前已产生的成本
             * @default 0
             */
            cancelled_cost_cny: number;
            /**
             * Price Note
             * @description 成本口径说明：单价、高峰/闲时
             * @default
             */
            price_note: string;
            /** Elapsed Ms */
            elapsed_ms: number;
            /** Avg Elapsed Ms */
            avg_elapsed_ms: number;
            /** By Status */
            by_status: {
                [key: string]: number;
            };
            /** By Provider */
            by_provider?: components["schemas"]["UsageProviderOut"][];
            /** By Model */
            by_model?: components["schemas"]["UsageModelOut"][];
            /** By Day */
            by_day: components["schemas"]["UsageDayOut"][];
        };
        /** UsageProviderOut */
        UsageProviderOut: {
            /** Provider */
            provider: string;
            /** Runs */
            runs: number;
            /** Tokens */
            tokens: number;
            /** Cost Cny */
            cost_cny: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthOut"];
                };
            };
        };
    };
    list_threads_api_v1_threads_get: {
        parameters: {
            query?: {
                /** @description 按标题或 ID 搜索 */
                q?: string | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_thread_api_v1_threads_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ThreadCreateIn"] | null;
            };
        };
        responses: {
            /** @description 创建成功 */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "trace_id": "tr_xxx",
                     *       "thread_id": "th_xxx",
                     *       "title": "整理周报",
                     *       "created_at": "2026-10-23T10:00:00+08:00",
                     *       "updated_at": "2026-10-23T10:00:00+08:00",
                     *       "pinned": false,
                     *       "message_count": 0,
                     *       "artifact_count": 0
                     *     }
                     */
                    "application/json": components["schemas"]["ThreadCreateOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_api_v1_threads__thread_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadDetailEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_thread_api_v1_threads__thread_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_thread_api_v1_threads__thread_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadUpdateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadCreateOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reorder_threads_api_v1_threads_reorder_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadReorderIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadReorderOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_delete_threads_api_v1_threads_bulk_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadBulkDeleteIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadBulkDeleteOut"];
                };
            };
            /** @description thread_ids 为空或超过 200 个（参数校验失败） */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_files_api_v1_threads__thread_id__files_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FileListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_files_api_v1_threads__thread_id__files_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_files_api_v1_threads__thread_id__files_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadResultOut"];
                };
            };
            /** @description 超过 max_upload_mb 限制 */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 扩展名 / MIME / magic bytes 校验失败 */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 文件解析失败或内容为空 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    delete_file_api_v1_files__file_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                file_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stream_run_api_v1_threads__thread_id__runs_stream_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RunRequestIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_runs_api_v1_runs_get: {
        parameters: {
            query?: {
                thread_id?: string | null;
                status?: string | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_thread_runs_api_v1_threads__thread_id__runs_get: {
        parameters: {
            query?: {
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_run_api_v1_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_run_api_v1_runs__run_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunCancelOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_run_api_v1_runs__run_id__retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_run_events_api_v1_runs__run_id__events_get: {
        parameters: {
            query?: {
                /** @description 只返回 seq > after 的事件 */
                after?: number;
            };
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunEventsOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stream_run_events_api_v1_runs__run_id__events_stream_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_approval_api_v1_threads__thread_id__approvals__approval_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApprovalRequestIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalDecisionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_artifacts_api_v1_artifacts_get: {
        parameters: {
            query?: {
                thread_id?: string | null;
                run_id?: string | null;
                /** @description docx | pdf | txt | xlsx | upload */
                type?: string | null;
                page?: number;
                page_size?: number;
                /** @description 是否把上传的素材也列出来（产物中心默认只列生成的产物） */
                include_uploads?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_trash_api_v1_artifacts_trash_get: {
        parameters: {
            query?: {
                page?: number;
                page_size?: number;
                /** @description 是否把上传素材也算进来（默认只列生成的产物） */
                include_uploads?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactTrashListOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_artifact_api_v1_artifacts__artifact_id__restore_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_artifact_api_v1_artifacts__artifact_id__purge_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    open_artifact_api_v1_artifacts__artifact_id__open_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    batch_delete_artifacts_api_v1_artifacts_batch_delete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactBatchDeleteIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactBatchDeleteOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_artifact_api_v1_artifacts__artifact_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_artifact_api_v1_artifacts__artifact_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_artifact_api_v1_artifacts__artifact_id__download_get: {
        parameters: {
            query?: {
                /** @description true 时 Content-Disposition 用 inline：PDF 交给浏览器内置阅读器，不当附件下载 */
                inline?: boolean;
            };
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_artifact_api_v1_artifacts__artifact_id__preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/html": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_artifact_api_v1_artifacts__artifact_id__regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_settings_api_v1_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsOut"];
                };
            };
        };
    };
    update_settings_api_v1_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdateIn"];
            };
        };
        responses: {
            /** @description 更新后的生效值 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "trace_id": "tr_xxx",
                     *       "model_provider": "mock",
                     *       "mock_mode": true,
                     *       "sources": {
                     *         "model_provider": "db",
                     *         "approval_rules": "db"
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["SettingsOut"];
                };
            };
            /** @description 不在白名单或类型不合法 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_models_api_v1_models_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelListOut"];
                };
            };
        };
    };
    upsert_model_api_v1_models_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModelCreateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_model_key_api_v1_models__model_id__key_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModelKeyIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelKeyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    model_balance_api_v1_models__model_id__balance_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelBalanceOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_model_api_v1_models__model_id__test_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelTestOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_templates_api_v1_templates_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateListOut"];
                };
            };
        };
    };
    create_template_api_v1_templates_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TemplateCreateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_template_api_v1_templates__template_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    render_template_api_v1_templates__template_id__render_post: {
        parameters: {
            query: {
                /** @description 目标会话 ID（使用该会话素材） */
                thread_id: string;
            };
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateRenderOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_skills_api_v1_skills_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillListOut"];
                };
            };
        };
    };
    list_skill_catalog_api_v1_skills_catalog_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillCatalogOut"];
                };
            };
        };
    };
    install_skill_from_catalog_api_v1_skills_catalog__skill_id__install_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                skill_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillInstallOut"];
                };
            };
            /** @description 技能库里没有这个技能 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 已经添加过 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_skill_api_v1_skills__skill_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                skill_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_skill_api_v1_skills__skill_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                skill_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SkillPatchIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillPatchOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    draft_skill_api_v1_skills_draft_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SkillDraftIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillDraftOut"];
                };
            };
            /** @description 没说清楚要什么 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_skill_api_v1_skills_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_import_skill_api_v1_skills_import_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description 文件为空或非 UTF-8 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 已有同名技能 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_prompt_packs_api_v1_prompt_packs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_projects_api_v1_projects_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    create_project_api_v1_projects_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectCreateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description 路径为空 / 不是目录 / 超出项目数量上限 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 这个文件夹已经在项目列表里 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_project_api_v1_projects__project_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_project_api_v1_projects__project_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectUpdateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_project_files_api_v1_projects__project_id__files_get: {
        parameters: {
            query?: {
                q?: string | null;
            };
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description 项目不存在或文件夹已被移动 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_project_api_v1_projects__project_id__reveal_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    browse_storage_api_v1_storage_browse_get: {
        parameters: {
            query?: {
                path?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description 当前目录、上级目录、子目录列表与可选起点 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    make_storage_dir_api_v1_storage_browse_mkdir_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StorageBrowseMkdirIn"];
            };
        };
        responses: {
            /** @description ok=false + error 表示没建成（重名 / 无权限） */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_storage_paths_api_v1_storage_paths_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    set_storage_paths_api_v1_storage_paths_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StorageSetIn"];
            };
        };
        responses: {
            /** @description 返回修改后生效的目录与文件数 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_storage_api_v1_storage_reveal_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StorageRevealIn"];
            };
        };
        responses: {
            /** @description opened=true 表示已唤起文件管理器 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_desktop_package_api_v1_desktop_package_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description available=false 表示服务端没有安装包，前端退回下载链接 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopPackageOut"];
                };
            };
        };
    };
    download_desktop_package_api_v1_desktop_package_download_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DesktopDownloadIn"];
            };
        };
        responses: {
            /** @description ok=false + error 表示没存成，记录会被清空 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDownloadOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_desktop_package_api_v1_desktop_package_reveal_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopActionOut"];
                };
            };
        };
    };
    open_desktop_package_api_v1_desktop_package_open_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopActionOut"];
                };
            };
        };
    };
    list_tools_api_v1_tools_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolListOut"];
                };
            };
        };
    };
    list_subagents_api_v1_subagents_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubagentListOut"];
                };
            };
        };
    };
    audit_thread_api_v1_threads__thread_id__audit_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    usage_summary_api_v1_usage_summary_get: {
        parameters: {
            query?: {
                range?: string;
                thread_id?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsageOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    provider_usage_api_v1_usage_provider_get: {
        parameters: {
            query?: {
                provider?: string;
                year?: number | null;
                month?: number | null;
                /** @description 跳过 60 秒缓存，强制重取 */
                force?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderUsageOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_provider_token_api_v1_usage_provider_token_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProviderTokenIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderTokenOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    clear_provider_token_api_v1_usage_provider_token_delete: {
        parameters: {
            query?: {
                provider?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderTokenOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    account_balance_api_v1_usage_balance_get: {
        parameters: {
            query?: {
                provider?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_audit_api_v1_audit_export_get: {
        parameters: {
            query?: {
                format?: string;
                thread_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description 审计导出文件（JSON 或 CSV） */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                    "text/csv": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_feedback_api_v1_feedback_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FeedbackOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    enhance_api_v1_prompts_enhance_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromptEnhanceIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptEnhanceOut"];
                };
            };
            /** @description 没写需求（全是空白） */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
